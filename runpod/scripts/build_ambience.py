"""
Procedural ambience beds for the renderer: remotion/public/sfx/amb-<name>.mp3.

No recording and no download: every bed is synthesised here from seeded noise
and small physical models (numpy), so the files carry no third-party rights
and rebuild identically (python scripts/build_ambience.py [name ...]).

Each bed is a 60-second loop made on a circle: noise is shaped by a
wrap-around STFT, every slow control (gusts, waves, flicker) is periodic over
the loop, every event (a drop, a bubble, a passing car, thunder) that runs
past the end continues at the start, and every steady tone completes whole
cycles. The last sample therefore leads into the first like any other pair:
the renderer's <Audio loop> repeats it with no seam and no crossfade dip.
48 kHz stereo, the channels' fine noise independent (width), their gusts and
waves shared and their events panned; loudness-matched to BED_LUFS
integrated with the true peak at or under PEAK_MAX; MP3 160 kbit/s.

sfx_meta.json (both copies: public/sfx and src/data) lists each bed with
category "ambience", loop true, duration, peak 0 (a bed has no hit), "lufs"
(its loudest 400 ms, the folder's convention), "lufsIntegrated" and "peakDb".
src/ambience.py plans them under the narration.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(ROOT, "remotion", "public", "sfx")
META_FILES = (os.path.join(SFX_DIR, "sfx_meta.json"), os.path.join(ROOT, "remotion", "src", "data", "sfx_meta.json"))

SR = 48000
LOOP_S = 60
N = SR * LOOP_S
NFFT, HOP = 2048, 512
COUNT = N // HOP                       # STFT frames on the circle (5625)
FRAME_RATE = SR / HOP
FREQS = np.fft.rfftfreq(NFFT, 1.0 / SR).astype(np.float32)
F = FREQS[None, :]
T = (np.arange(COUNT) * HOP / SR).astype(np.float32)          # frame centres (s)
BED_LUFS = -24.0
PEAK_MAX = -3.0
BITRATE = "160k"

Stereo = Tuple[np.ndarray, np.ndarray]


# --------------------------------------------------------------------------- #
# Circular building blocks
# --------------------------------------------------------------------------- #

def white(rng) -> np.ndarray:
    return rng.standard_normal(N).astype(np.float32)


def lf(rng, cutoff: float, n: int = COUNT, rate: float = FRAME_RATE) -> np.ndarray:
    """A smooth random control signal, periodic over the loop: energy under `cutoff` Hz, zero mean, unit std."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / rate)
    spec *= 1.0 / np.sqrt(1.0 + (f / max(cutoff, 1e-6)) ** 8)
    spec[0] = 0.0
    y = np.fft.irfft(spec, n)
    return ((y - y.mean()) / (y.std() + 1e-12)).astype(np.float32)


def at_samples(ctrl: np.ndarray) -> np.ndarray:
    """A frame-rate control at every sample, interpolated around the circle."""
    pos = np.arange(N, dtype=np.float64) / HOP
    return np.interp(pos, np.arange(COUNT + 1), np.append(ctrl, ctrl[0])).astype(np.float32)


def tilt(f, slope: float, ref: float = 1000.0):
    """Amplitude f^slope against `ref` (pink -0.5, brown -1), 0 at DC."""
    f = np.asarray(f, dtype=np.float32)
    return np.where(f > 0, (np.maximum(f, 1e-3) / ref) ** slope, 0.0).astype(np.float32)


def lp(f, fc, order: int = 2):
    return 1.0 / np.sqrt(1.0 + (np.asarray(f) / fc) ** (2 * order))


def hp(f, fc, order: int = 2):
    return 1.0 / np.sqrt(1.0 + (fc / np.maximum(np.asarray(f), 1e-3)) ** (2 * order))


def bump(f, fc, bw):
    return np.exp(-0.5 * ((np.asarray(f) - fc) / bw) ** 2)


_WIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(NFFT) / NFFT)).astype(np.float32)


def shape(x: np.ndarray, gain) -> np.ndarray:
    """
    Time-varying spectral shaping on the circle: frame i (centred on sample
    i*HOP) of the wrapped signal times gain[i] (frames x bins, or one row),
    overlap-added back around the circle (Hann, 75% overlap).
    """
    ext = np.concatenate([x[-NFFT:], x, x[:NFFT]]).astype(np.float32)
    view = np.lib.stride_tricks.sliding_window_view(ext, NFFT)[NFFT // 2::HOP][:COUNT]
    g = np.asarray(gain, dtype=np.float32)
    out_ext = np.zeros(len(ext), np.float32)
    step = 512
    for a in range(0, COUNT, step):
        b = min(COUNT, a + step)
        spec = np.fft.rfft(view[a:b] * _WIN, axis=1)
        spec *= g[a:b] if g.ndim == 2 and g.shape[0] > 1 else g.reshape(1, -1)
        y = np.fft.irfft(spec, n=NFFT, axis=1).astype(np.float32) * _WIN
        for i in range(b - a):
            s = (a + i) * HOP + NFFT // 2
            out_ext[s:s + NFFT] += y[i]
    out = out_ext[NFFT:NFFT + N].copy()
    out[N - NFFT:] += out_ext[:NFFT]
    out[:NFFT] += out_ext[NFFT + N:NFFT + N + NFFT]
    return out / 1.5


def shape_static(x: np.ndarray, gain_fn: Callable) -> np.ndarray:
    """A fixed filter over the whole circle (one FFT): gain_fn(freqs) -> amplitude."""
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    return np.fft.irfft(np.fft.rfft(x) * gain_fn(f), len(x)).astype(np.float32)


def add_event(out: np.ndarray, pos: int, wave: np.ndarray) -> None:
    """Add `wave` at `pos`, the part past the end continuing at the start."""
    p = int(pos) % N
    n = len(wave)
    end = p + n
    if end <= N:
        out[p:end] += wave
    else:
        k = N - p
        out[p:] += wave[:k]
        out[:n - k] += wave[k:]


def reverb(x: np.ndarray, rng, rt60: float, mix: float, darken: float = 5000.0, predelay: float = 0.012) -> np.ndarray:
    """A circular convolution with an exponentially decaying noise tail."""
    n = int(SR * rt60 * 1.1)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-6.91 * t / rt60)
    ir[: int(predelay * SR)] = 0.0
    f = np.fft.rfftfreq(N, 1.0 / SR)
    wet = np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(ir, N) * lp(f, darken, 1), N).astype(np.float32)
    wet *= float(np.std(x) / (np.std(wet) + 1e-12))
    return ((1.0 - mix) * x + mix * wet).astype(np.float32)


def rms(x) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)) + 1e-20))


def pan(x: np.ndarray, p: float) -> Stereo:
    """Equal-power pan, p in [-1, 1]."""
    a = (p + 1.0) * math.pi / 4.0
    return x * math.cos(a), x * math.sin(a)


def periodic_hz(f: float) -> float:
    """The nearest frequency that completes whole cycles in the loop."""
    return round(f * LOOP_S) / LOOP_S


def soft_limit(x: np.ndarray, crest_db: float) -> np.ndarray:
    """Round off peaks more than `crest_db` over the sound's level (its active part), tanh-soft."""
    active = x[np.abs(x) > 1e-4 * (np.abs(x).max() + 1e-12)]
    lim = rms(active if len(active) else x) * 10 ** (crest_db / 20.0)
    return (lim * np.tanh(x / lim)).astype(np.float32)


def drops(rng, per_second: float, sigma: float, decay_ms: Tuple[float, float], shapes: int = 4) -> np.ndarray:
    """
    Many small impacts (rain drops, fire crackles): a random train whose
    amplitudes spread lognormally (capped at 3x the median: no lone shot
    stands out) through a few short decaying-noise drop shapes.
    """
    out = np.zeros(N, np.float32)
    for _ in range(shapes):
        d = rng.uniform(*decay_ms) / 1000.0
        n = max(16, int(d * 7 * SR))
        t = np.arange(n) / SR
        kern = rng.standard_normal(n) * np.exp(-t / d) * (1.0 - np.exp(-t / 0.0004))
        x = np.zeros(N, np.float32)
        pos = rng.uniform(0, N, int(per_second / shapes * LOOP_S)).astype(int)
        np.add.at(x, pos, np.minimum(np.exp(rng.normal(0.0, sigma, len(pos))), 3.0).astype(np.float32))
        out += np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(kern, N), N).astype(np.float32)
    return out


# --------------------------------------------------------------------------- #
# The beds
# --------------------------------------------------------------------------- #

def bed_wind(rng) -> Stereo:
    """Open-air wind (desert, canyon rim, aerial shots): slow gusts open and close
    a low-passed rush, a faint whistle in the strong ones, air hiss on top."""
    g = (0.5 + 0.5 * np.tanh(1.3 * lf(rng, 0.06))).astype(np.float32)
    flutter = 0.12 * lf(rng, 0.5)
    amp = np.clip(0.35 + 0.65 * g + flutter, 0.2, 1.15)
    # The rush lives in 150-1500 Hz (a phone speaker plays it); little under 80 Hz.
    fc = 320.0 + 1150.0 * g ** 1.3
    fw = 600.0 + 260.0 * lf(rng, 0.04)
    ww = np.clip((g - 0.6) / 0.4, 0.0, 1.0) ** 2 * 0.4
    base = tilt(F, -0.35) * lp(F, fc[:, None], 2) * hp(F, 80.0, 2)
    whistle = ww[:, None] * bump(F, fw[:, None], 18.0) * 0.6
    hiss = 0.07 * g[:, None] * hp(F, 2500.0, 2) * lp(F, 9000.0, 2)
    gain = amp[:, None] * (base + whistle + hiss)
    return shape(white(rng), gain), shape(white(rng), gain)


def _waves(rng, every: Tuple[float, float], rise: Tuple[float, float], decay: Tuple[float, float],
           floor: float) -> np.ndarray:
    """A wave envelope on the frame grid: quick rises, slow washes, around the circle."""
    env = np.zeros(COUNT, np.float32)
    t = float(rng.uniform(0.0, every[0]))
    while t < LOOP_S:
        a = rng.uniform(0.55, 1.0)
        r, d = rng.uniform(*rise), rng.uniform(*decay)
        n = int((r + 5 * d) * FRAME_RATE)
        tt = np.arange(n) / FRAME_RATE
        shape_ = np.where(tt < r, np.sin(0.5 * np.pi * tt / r) ** 2, np.exp(-(tt - r) / d)).astype(np.float32)
        idx = (int(t * FRAME_RATE) + np.arange(n)) % COUNT
        np.add.at(env, idx, a * shape_)
        t += rng.uniform(*every)
    return np.clip(floor + env, 0.0, 1.6).astype(np.float32)


def _burst(rng, length_s: float, fc: float, bw: float, attack_s: float, decay_s: float) -> np.ndarray:
    n = max(16, int(length_s * SR))
    t = np.arange(n) / SR
    env = (1.0 - np.exp(-t / max(attack_s, 1e-4))) * np.exp(-t / decay_s)
    noise = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    return (np.fft.irfft(np.fft.rfft(noise) * bump(f, fc, bw), n) * env).astype(np.float32)


def bed_water(rng) -> Stereo:
    """Water at a shore or a dock: gentle washes every few seconds, brighter as
    each one breaks, small laps and splashes between them."""
    # Washes that swell in over half a second or more and draw back slowly, at
    # irregular intervals, over a steady lap (never a regular surf).
    w = _waves(rng, (1.8, 6.2), (0.45, 0.95), (1.4, 3.0), 0.45)
    bright = 900.0 + 1800.0 * np.clip(w, 0.0, 1.3)
    gain = w[:, None] * tilt(F, -0.3) * hp(F, 110.0, 2) * lp(F, bright[:, None], 2)
    left, right = shape(white(rng), gain), shape(white(rng), gain)
    laps_l, laps_r = np.zeros(N, np.float32), np.zeros(N, np.float32)
    w_s = at_samples(w)
    for pos in np.sort(rng.uniform(0, N, int(2.6 * LOOP_S))).astype(int):
        b = _burst(rng, rng.uniform(0.1, 0.25), rng.uniform(450, 1400), rng.uniform(150, 450), 0.01,
                   rng.uniform(0.025, 0.08))
        b *= rng.uniform(0.3, 1.0) * float(w_s[pos])
        l, r = pan(b, rng.uniform(-0.8, 0.8))
        add_event(laps_l, pos, l)
        add_event(laps_r, pos, r)
    k = 0.55 * rms(left) / (rms(laps_l) + 1e-12)
    return left + k * laps_l, right + k * laps_r


def _bubble(rng) -> np.ndarray:
    f0 = 10 ** rng.uniform(math.log10(500.0), math.log10(2600.0))
    dur = rng.uniform(0.006, 0.026)
    n = int(dur * 4 * SR)
    t = np.arange(n) / SR
    freq = f0 * (1.0 + 0.5 * np.minimum(t / dur, 1.5))         # a bubble's pitch rises as it closes
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return (np.sin(phase) * np.exp(-t / (dur / 2.5)) * (1.0 - np.exp(-t / 0.0006))).astype(np.float32)


def bed_river(rng) -> Stereo:
    """A river or stream running over rocks: a steady rush with a body around
    1 kHz, its surface fluttering, and a dense scatter of small bubbles."""
    flutter = 1.0 + 0.12 * lf(rng, 6.0)
    gain = flutter[:, None] * tilt(F, -0.25) * hp(F, 140.0, 2) * lp(F, 7500.0, 2) * (1.0 + 0.9 * bump(F, 1100.0, 650.0))
    left, right = shape(white(rng), gain), shape(white(rng), gain)
    bl, br = np.zeros(N, np.float32), np.zeros(N, np.float32)
    for pos in rng.uniform(0, N, int(48 * LOOP_S)).astype(int):
        b = _bubble(rng) * float(np.exp(rng.normal(0.0, 0.6)))
        l, r = pan(b, rng.uniform(-0.9, 0.9))
        add_event(bl, pos, l)
        add_event(br, pos, r)
    k = 0.45 * rms(left) / (rms(bl) + 1e-12)
    return left + k * bl, right + k * br


def _train(rng, per_second: float, sigma: float) -> np.ndarray:
    x = np.zeros(N, np.float32)
    pos = rng.uniform(0, N, int(per_second * LOOP_S)).astype(int)
    np.add.at(x, pos, (np.exp(rng.normal(0.0, sigma, len(pos))) * rng.choice([-1.0, 1.0], len(pos))).astype(np.float32))
    return x


def bed_rain(rng, heavy: bool = False) -> Stereo:
    """Steady rain: a high hiss, a dense spray of drop clicks, a softer patter
    on hard surfaces and a little low body."""
    swell = 1.0 + 0.12 * lf(rng, 0.08)
    hiss = swell[:, None] * hp(F, 900.0, 2) * lp(F, 11000.0, 2) * (0.6 + 0.6 * bump(F, 4500.0, 2600.0))
    out = []
    for _ in range(2):
        h = shape(white(rng), hiss)
        spray = shape_static(drops(rng, 700.0 if heavy else 480.0, 0.45, (0.5, 2.0)),
                             lambda f: hp(f, 1800.0, 2) * lp(f, 9000.0, 1))
        patter = shape_static(drops(rng, 36.0 if heavy else 26.0, 0.4, (2.0, 6.0)),
                              lambda f: bump(f, 900.0, 500.0))
        body = shape_static(rng.standard_normal(N).astype(np.float32), lambda f: tilt(f, -0.8) * lp(f, 260.0, 2))
        x = (h / rms(h) + 0.8 * spray / rms(spray) + 0.35 * patter / rms(patter)
             + (0.45 if heavy else 0.3) * body / rms(body))
        out.append(x.astype(np.float32))
    return out[0], out[1]


def _thunder(rng, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    env = np.zeros(n)
    for _ in range(6):
        on = rng.uniform(0.0, seconds * 0.35)
        a, d = rng.uniform(0.35, 1.0), rng.uniform(0.6, 1.8)
        env += a * (t > on) * np.exp(-np.maximum(t - on, 0) / d) * (1.0 - np.exp(-np.maximum(t - on, 0) / 0.18))
    env *= np.exp(-t / (seconds * 0.6))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    rumble = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) * tilt(f, -1.0, 100.0) * lp(f, 160.0, 2) * hp(f, 25.0, 2), n)
    crack = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) * bump(f, 600.0, 450.0), n) * np.exp(-t / 0.25)
    x = rumble / (np.abs(rumble).max() + 1e-12) * env + 0.15 * crack / (np.abs(crack).max() + 1e-12)
    return x.astype(np.float32)


def bed_storm(rng) -> Stereo:
    """A rain storm: heavy rain, low gusts under it and two distant thunder rolls
    (never close: their loudest moment a few dB over the rain)."""
    l, r = bed_rain(rng, heavy=True)
    wl, wr = bed_wind(rng)
    l = l / rms(l) + 0.35 * wl / rms(wl)
    r = r / rms(r) + 0.35 * wr / rms(wr)
    for at in (17.0, 43.0):
        th = _thunder(rng, rng.uniform(6.0, 8.0))
        th *= 2.6 / (np.abs(th).max() + 1e-12)
        tl, tr = pan(th, rng.uniform(-0.4, 0.4))
        add_event(l, int(at * SR), tl)
        add_event(r, int(at * SR), tr)
    return l, r


_VOWELS = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480), (660, 1720, 2410),
           (570, 840, 2410), (440, 1020, 2240), (490, 1350, 1690)]


def _talker(rng) -> np.ndarray:
    """One voice in the room: phrases of syllables, each with its own vowel, a wandering pitch."""
    female = rng.random() < 0.45
    f0base = rng.uniform(175, 235) if female else rng.uniform(95, 140)
    fscale = 1.15 if female else 1.0
    env = np.zeros(N, np.float32)
    f1 = np.zeros(COUNT, np.float32)
    f2 = np.zeros(COUNT, np.float32)
    f3 = np.zeros(COUNT, np.float32)
    t = rng.uniform(0.0, 2.0)
    vow = _VOWELS[0]
    last = 0
    while t < LOOP_S:
        phrase_end = t + rng.uniform(1.2, 3.8)
        while t < phrase_end:
            d = rng.uniform(0.11, 0.26)
            n = int(d * SR)
            s = np.sin(np.pi * np.arange(n) / n) ** 1.5 * rng.uniform(0.6, 1.0)
            add_event(env, int(t * SR), s.astype(np.float32))
            vow = _VOWELS[rng.integers(len(_VOWELS))]
            a = int(t * FRAME_RATE)
            for k in range(last, a + 1):
                kk = k % COUNT
                f1[kk], f2[kk], f3[kk] = vow[0] * fscale, vow[1] * fscale, vow[2] * fscale
            last = a + 1
            t += d + rng.uniform(0.0, 0.05)
        t = phrase_end + rng.uniform(0.3, 1.4)
    for k in range(last, COUNT):
        f1[k], f2[k], f3[k] = vow[0] * fscale, vow[1] * fscale, vow[2] * fscale
    # Smooth the formant moves (~40 ms).
    kern = np.hanning(9)
    kern /= kern.sum()
    f1, f2, f3 = (np.convolve(np.concatenate([x[-8:], x, x[:8]]), kern, "same")[8:-8] for x in (f1, f2, f3))
    # float64: a float32 running phase drifted 4 rad over the minute and clicked at the seam.
    f0 = f0base * (1.0 + 0.07 * at_samples(lf(rng, 2.5)).astype(np.float64))
    total = float(np.sum(f0) / SR)
    f0 *= round(total) / total                        # whole cycles round the loop
    phase = 2 * np.pi * np.cumsum(f0) / SR
    k_max = int(4000.0 / (f0base * 1.25))
    half = np.sin(phase / 2.0)
    dirichlet = np.where(np.abs(half) < 1e-6, k_max, np.sin((k_max + 0.5) * phase) / (2.0 * np.where(np.abs(half) < 1e-6, 1.0, half)) - 0.5)
    src = dirichlet.astype(np.float32) / k_max + 0.08 * rng.standard_normal(N).astype(np.float32)
    gain = tilt(F, -1.0, 300.0) * (bump(F, f1[:, None], 70.0) + 0.7 * bump(F, f2[:, None], 110.0)
                                   + 0.35 * bump(F, f3[:, None], 160.0) + 0.03) * hp(F, 90.0, 2)
    # A synthetic glottis rings higher than a throat (21 dB peaks): rounded off at a voice's 12 dB.
    return soft_limit(shape(src, gain), 12.0) * env


def bed_crowd(rng) -> Stereo:
    """A room or square of people talking at once, too far to make out a word:
    two dozen voices, each its own pitch and rhythm, in a reverberant space."""
    left, right = np.zeros(N, np.float32), np.zeros(N, np.float32)
    for _ in range(24):
        v = _talker(rng) * float(10 ** (-rng.uniform(0.0, 6.0) / 20.0))
        l, r = pan(v, rng.uniform(-0.85, 0.85))
        left += l
        right += r
    left = reverb(left, rng, 0.9, 0.4)
    right = reverb(right, rng, 0.9, 0.4)
    dist = lambda f: lp(f, 3400.0, 2) * hp(f, 120.0, 2)     # noqa: E731 - far away: no air, no boom
    return shape_static(left, dist), shape_static(right, dist)


def bed_city(rng) -> Stereo:
    """A city street from a little way off: traffic rumble, cars passing left to
    right and back, and people somewhere in it."""
    roll = 1.0 + 0.2 * lf(rng, 0.08)
    # The distant traffic wash in the band a phone plays (250 Hz-2 kHz), its low rumble kept small.
    base = roll[:, None] * (0.45 * tilt(F, -0.9) * lp(F, 300.0, 2) * hp(F, 45.0, 2)
                            + tilt(F, -0.3) * bump(F, 700.0, 600.0) * hp(F, 150.0, 2))
    gl = np.repeat(base.astype(np.float32), 1, axis=0).copy()
    gr = gl.copy()
    car = tilt(F, -0.4) * lp(F, 3200.0, 2) * hp(F, 120.0, 2)
    centres = np.sort(rng.uniform(0.0, LOOP_S, 7))
    for tc in centres:
        sigma = rng.uniform(1.0, 1.8)
        a = rng.uniform(0.6, 1.3)
        direction = rng.choice([-1.0, 1.0])
        dt = ((T - tc + LOOP_S / 2) % LOOP_S) - LOOP_S / 2              # around the circle
        amp = a * np.exp(-0.5 * (dt / sigma) ** 2)
        p = np.clip(0.5 + direction * dt / (3.0 * sigma), 0.0, 1.0)
        fc = 600.0 + 300.0 * (1.0 - p if direction > 0 else p)          # a falling note as it goes by
        spec = car * (1.0 + 0.8 * bump(F, fc[:, None], 350.0))
        gl += (amp * np.cos(p * np.pi / 2))[:, None] * spec
        gr += (amp * np.sin(p * np.pi / 2))[:, None] * spec
    left, right = shape(white(rng), gl), shape(white(rng), gr)
    cl, cr = bed_crowd(rng)
    k = 0.22 * rms(left) / (rms(cl) + 1e-12)
    return left + k * cl, right + k * cr


def bed_fire(rng) -> Stereo:
    """A fire burning: a low roar that flickers, a hiss, sharp crackles and the
    odd deeper pop of wood."""
    flick = 0.8 + 0.25 * lf(rng, 2.5)
    roar = flick[:, None] * tilt(F, -0.7) * lp(F, 520.0, 2) * hp(F, 60.0, 2)
    sizzle = (0.6 + 0.4 * np.tanh(lf(rng, 6.0)))[:, None] * hp(F, 3000.0, 2) * lp(F, 10000.0, 2)
    out = []
    for _ in range(2):
        r = shape(white(rng), roar)
        s = shape(white(rng), sizzle)
        crackle = shape_static(drops(rng, 34.0, 0.6, (0.4, 2.0)), lambda f: bump(f, 2600.0, 1800.0) * hp(f, 700.0, 2))
        fizz = shape_static(drops(rng, 160.0, 0.35, (0.2, 0.8)), lambda f: hp(f, 2500.0, 2))
        pops = shape_static(drops(rng, 1.3, 0.35, (8.0, 20.0), shapes=2), lambda f: bump(f, 420.0, 160.0))
        x = (r / rms(r) + 0.18 * s / rms(s) + 0.5 * crackle / rms(crackle) + 0.15 * fizz / rms(fizz)
             + 0.3 * pops / rms(pops))
        out.append(x.astype(np.float32))
    return out[0], out[1]


def bed_machinery(rng) -> Stereo:
    """A machine hall (a dam's powerhouse, a pump station, a plant): mains hum
    and its harmonics, a turbine whine, a rotating mechanical churn, a big room."""
    t = np.arange(N) / SR
    hum = np.zeros(N, np.float64)
    for h, a in ((1, 1.0), (2, 0.6), (3, 0.35), (4, 0.22), (5, 0.12), (6, 0.08)):
        fq = periodic_hz(60.0 * h + rng.uniform(-0.08, 0.08))
        hum += a * np.sin(2 * np.pi * fq * t + rng.uniform(0, 2 * np.pi))
    hum *= 1.0 + 0.06 * np.sin(2 * np.pi * periodic_hz(0.07) * t)
    whine = 0.05 * np.sin(2 * np.pi * periodic_hz(1440.0) * t + 3.0 * np.sin(2 * np.pi * periodic_hz(0.3) * t))
    churn_mod = 1.0 + 0.25 * np.sin(2 * np.pi * periodic_hz(9.0) * T)
    churn_gain = churn_mod[:, None] * tilt(F, -0.5) * hp(F, 90.0, 2) * lp(F, 1600.0, 2)
    out = []
    for _ in range(2):
        churn = shape(white(rng), churn_gain)
        x = 0.7 * hum / rms(hum) + 0.25 * whine / rms(whine) + churn / rms(churn)
        out.append(reverb(x.astype(np.float32), rng, 1.6, 0.45, darken=3500.0))
    return out[0], out[1]


RISER = "riser-soft"
RISER_SECONDS = 1.8
RISER_PEAK = 1.6
RISER_LUFS = -20.0            # its loudest 400 ms: the folder's matched level (sfxplan.SFX_REF_LUFS)
RISER_PEAK_MAX = -3.5


def make_riser(rng) -> Stereo:
    """
    A soft swell into a reveal: airy noise whose band climbs from 1.4 to
    6 kHz - over the voice's own 300-3000 Hz, so the words under it stay
    clear - with a faint sub swell under it, rising for 1.6 s to its peak and
    gone 0.2 s later. No pitch, no hit: the reveal's own sound is the hit.
    """
    n = int(RISER_SECONDS * SR)
    t = np.arange(n) / SR
    up = np.clip(t / RISER_PEAK, 0.0, 1.0)
    env = np.where(t <= RISER_PEAK, 10 ** ((-34.0 + 34.0 * up ** 1.7) / 20.0),
                   np.cos(0.5 * np.pi * np.clip((t - RISER_PEAK) / (RISER_SECONDS - RISER_PEAK), 0, 1)) ** 2)
    pad = NFFT
    frames = 1 + (n + 2 * pad - NFFT) // HOP
    tf = (np.arange(frames) * HOP + NFFT / 2 - pad) / SR
    centre = 1400.0 + 4600.0 * np.clip(tf / RISER_PEAK, 0.0, 1.0) ** 1.5
    air = bump(F, centre[:, None], 0.45 * centre[:, None]) * hp(F, 900.0, 2)
    sub = 0.35 * np.clip(tf / RISER_PEAK, 0.0, 1.0)[:, None] ** 2 * tilt(F, -1.0, 60.0) * lp(F, 90.0, 2) * hp(F, 28.0, 2)
    gain = (air + sub).astype(np.float32)
    out = []
    for _ in range(2):
        x = np.concatenate([np.zeros(pad, np.float32), rng.standard_normal(n).astype(np.float32),
                            np.zeros(pad, np.float32)])
        view = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP][:frames]
        y = np.fft.irfft(np.fft.rfft(view * _WIN, axis=1) * gain[:frames], n=NFFT, axis=1).astype(np.float32) * _WIN
        acc = np.zeros(len(x), np.float32)
        for i in range(frames):
            acc[i * HOP:i * HOP + NFFT] += y[i]
        out.append((acc[pad:pad + n] / 1.5 * env).astype(np.float32))
    return out[0], out[1]


def build_riser() -> Dict[str, float]:
    rng = np.random.default_rng(1001)
    left, right = make_riser(rng)
    x = np.stack([left, right], axis=1).astype(np.float32)
    x /= float(np.abs(x).max() + 1e-12)
    first = _measure(x.tobytes())
    gain_db = min(RISER_LUFS - first["lufs"], RISER_PEAK_MAX - first["truePeak"])
    x *= float(10 ** (gain_db / 20.0))
    meas = _measure(x.tobytes())
    out = os.path.join(SFX_DIR, f"{RISER}.mp3")
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", "192k", out], input=x.tobytes(), check=True)
    peak_db = 20.0 * math.log10(float(np.abs(x).max()) + 1e-12)
    return {"duration": RISER_SECONDS, "peak": RISER_PEAK, "category": "riser", "loop": False,
            "lufs": round(meas["lufs"], 1), "peakDb": round(peak_db, 1), "truePeak": round(meas["truePeak"], 1)}


BEDS: Dict[str, Tuple[int, Callable]] = {
    "wind": (101, bed_wind), "water": (202, bed_water), "river": (303, bed_river), "rain": (404, bed_rain),
    "storm": (505, bed_storm), "city": (606, bed_city), "crowd": (707, bed_crowd), "fire": (808, bed_fire),
    "machinery": (909, bed_machinery),
}


# --------------------------------------------------------------------------- #
# Level, file, meta
# --------------------------------------------------------------------------- #

def _measure(raw: bytes) -> Dict[str, float]:
    # The per-100 ms log (momentary loudness "M:") is printed at the verbose log level only.
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "verbose", "-f", "f32le", "-ar", str(SR), "-ac", "2",
                        "-i", "-", "-af", "ebur128=peak=true:framelog=verbose", "-f", "null", "-"],
                       input=raw, capture_output=True)
    err = p.stderr.decode("utf-8", "replace")
    summary = err[err.rfind("Summary"):]
    i = float(re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", summary).group(1))
    tp = float(re.search(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", summary).group(1))
    moments = [float(m) for m in re.findall(r"\bM:\s*(-?\d+(?:\.\d+)?)", err[:err.rfind("Summary")])]
    return {"lufsIntegrated": i, "truePeak": tp, "lufs": max(moments) if moments else i}


# A bed is a texture: no lone click or knock may stand far over it (a field
# recording of rain peaks 15-20 dB over its level); the storm's thunder is
# meant to rise over the rain.
CREST_DB = 18.0
CREST_DB_BY_NAME = {"storm": 24.0}


def build(name: str) -> Dict[str, float]:
    seed, fn = BEDS[name]
    rng = np.random.default_rng(seed)
    left, right = fn(rng)
    crest = CREST_DB_BY_NAME.get(name, CREST_DB)
    left, right = soft_limit(left, crest), soft_limit(right, crest)
    x = np.stack([left, right], axis=1).astype(np.float32)
    x /= float(np.abs(x).max() + 1e-12)
    first = _measure(x.tobytes())
    gain_db = BED_LUFS - first["lufsIntegrated"]
    gain_db = min(gain_db, PEAK_MAX - first["truePeak"])
    x *= float(10 ** (gain_db / 20.0))
    meas = _measure(x.tobytes())
    out = os.path.join(SFX_DIR, f"amb-{name}.mp3")
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", BITRATE, out], input=x.tobytes(), check=True)
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    samples = len(dec) // 8
    peak_db = 20.0 * math.log10(float(np.abs(x).max()) + 1e-12)
    return {"duration": round(samples / SR, 3), "samples": samples, "peak": 0.0, "category": "ambience", "loop": True,
            "lufs": round(meas["lufs"], 1), "lufsIntegrated": round(meas["lufsIntegrated"], 1),
            "peakDb": round(peak_db, 1), "truePeak": round(meas["truePeak"], 1)}


META_KEYS = ("category", "duration", "loop", "lufs", "lufsIntegrated", "peak", "peakDb")


def write_meta(entries: Dict[str, Dict[str, float]]) -> None:
    """Add or replace the entries (by file name) in both copies of sfx_meta.json, keeping their layout."""
    for path in META_FILES:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        meta = json.loads(text)
        for name, e in entries.items():
            meta[name] = {k: e[k] for k in META_KEYS if k in e}
        indent = 2 if "\n  \"" in text else None
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(meta.items())), fh, indent=indent, sort_keys=True)
            if text.endswith("\n"):
                fh.write("\n")


if __name__ == "__main__":
    names = sys.argv[1:] or list(BEDS) + [RISER]
    built = {}
    for nm in names:
        if nm == RISER:
            e = build_riser()
            built[RISER] = e
            print(f"{RISER}: {e['duration']} s, loudest 400 ms {e['lufs']} LUFS, true peak {e['truePeak']} dBFS",
                  flush=True)
            continue
        e = build(nm)
        built[f"amb-{nm}"] = e
        print(f"amb-{nm}: {e['duration']} s ({e['samples']} samples), {e['lufsIntegrated']} LUFS, "
              f"loudest 400 ms {e['lufs']}, true peak {e['truePeak']} dBFS", flush=True)
    write_meta(built)
