"""Tool 4 – SFX-Synthesizer: Whoosh, Klick, Pop, Riser (+ Impact, Ding) als lizenzfreie WAV (Phase 6.2)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .common import DEFAULT_SR, ToolError, write_wav

SR = DEFAULT_SR


def _env(n: int, attack: float, release: float, curve: float = 2.0) -> np.ndarray:
    """Hüllkurve: Attack-Anteil und Release-Anteil (0–1) der Länge n."""
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    s = max(0, n - a - r)
    up = np.linspace(0, 1, a) ** curve
    down = np.linspace(1, 0, r) ** curve
    return np.concatenate([up, np.ones(s), down])[:n]


def _svf_bandpass(x: np.ndarray, cutoff: np.ndarray, q: float = 1.5) -> np.ndarray:
    """State-Variable-Filter mit zeitvariabler Grenzfrequenz (Bandpass)."""
    y = np.zeros_like(x)
    low = band = 0.0
    damp = 1.0 / q
    f = 2 * np.sin(np.pi * np.clip(cutoff, 20, SR / 6) / SR)
    for i in range(len(x)):
        high = x[i] - low - damp * band
        band += f[i] * high
        low += f[i] * band
        y[i] = band
    return y


def _normalize(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    peak = np.max(np.abs(x)) or 1.0
    return x / peak * (10 ** (peak_db / 20))


def _stereo(x: np.ndarray, pan: np.ndarray | float) -> np.ndarray:
    pan = np.clip(pan, -1, 1)
    left = x * np.cos((pan + 1) * np.pi / 4)
    right = x * np.sin((pan + 1) * np.pi / 4)
    return np.stack([left, right], axis=1)


def whoosh(duration: float = 0.6, pitch: float = 1.0, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    n = int(SR * duration)
    t = np.linspace(0, 1, n)
    noise = rng.standard_normal(n)
    sweep = (300 + 2700 * np.sin(np.pi * t) ** 1.5) * pitch
    y = _svf_bandpass(noise, sweep, q=1.2) * _env(n, 0.45, 0.55, 1.6)
    return _stereo(_normalize(y), np.linspace(-0.6, 0.6, n))


def click(duration: float = 0.05, pitch: float = 1.0, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    n = int(SR * duration)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 2200 * pitch * t) * np.exp(-t * 180)
    tick = rng.standard_normal(n) * np.exp(-t * 900) * 0.6
    y = _normalize(tone + tick)
    return _stereo(y, 0.0)


def pop(duration: float = 0.15, pitch: float = 1.0, rng=None) -> np.ndarray:
    n = int(SR * duration)
    t = np.arange(n) / SR
    freq = (900 * np.exp(-t * 30) + 250) * pitch
    phase = 2 * np.pi * np.cumsum(freq) / SR
    y = np.sin(phase) * np.exp(-t * 28) * _env(n, 0.02, 0.3, 1.0)
    return _stereo(_normalize(y), 0.0)


def riser(duration: float = 2.0, pitch: float = 1.0, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    n = int(SR * duration)
    t = np.linspace(0, 1, n)
    freq = (120 * (2 ** (t * 3))) * pitch  # 3 Oktaven nach oben
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = 0.6 * np.sin(phase) + 0.25 * np.sin(2 * phase + 0.3) + 0.15 * np.sin(3.01 * phase)
    noise = _svf_bandpass(rng.standard_normal(n), 400 + 6000 * t ** 2, q=0.9) * 0.8
    y = (tone + noise) * (t ** 2.2) * _env(n, 0.0, 0.02, 1.0)
    return _stereo(_normalize(y), 0.0)


def impact(duration: float = 1.2, pitch: float = 1.0, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    n = int(SR * duration)
    t = np.arange(n) / SR
    freq = (110 * np.exp(-t * 6) + 40) * pitch
    phase = 2 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t * 3.5)
    crack = rng.standard_normal(n) * np.exp(-t * 60) * 0.5
    y = np.tanh(2.0 * (body + crack))
    return _stereo(_normalize(y), 0.0)


def ding(duration: float = 1.0, pitch: float = 1.0, rng=None) -> np.ndarray:
    n = int(SR * duration)
    t = np.arange(n) / SR
    f = 1320 * pitch
    y = sum(a * np.sin(2 * np.pi * f * m * t) * np.exp(-t * d)
            for m, a, d in [(1, 1.0, 4), (2.76, 0.4, 7), (5.4, 0.2, 11)])
    y *= _env(n, 0.003, 0.05, 1.0)
    return _stereo(_normalize(y), 0.0)


SOUNDS = {"whoosh": whoosh, "klick": click, "click": click, "pop": pop, "riser": riser,
          "impact": impact, "ding": ding}
DEFAULT_DURATION = {"whoosh": 0.6, "klick": 0.05, "click": 0.05, "pop": 0.15, "riser": 2.0,
                    "impact": 1.2, "ding": 1.0}


def generate(kind: str, duration: float | None = None, pitch: float = 1.0, seed: int | None = None,
             gain_db: float = -1.0) -> np.ndarray:
    kind = kind.lower()
    if kind not in SOUNDS:
        raise ToolError(f"Unbekannter Sound '{kind}'. Möglich: {', '.join(sorted(set(SOUNDS)))}")
    dur = duration or DEFAULT_DURATION[kind]
    if not 0.01 <= dur <= 30:
        raise ToolError("Dauer muss zwischen 0.01 und 30 Sekunden liegen.")
    rng = np.random.default_rng(seed)
    y = SOUNDS[kind](dur, pitch, rng)
    return _normalize(y, gain_db)


def main(args) -> int:
    out_dir = Path(args.ordner)
    kinds = ["whoosh", "klick", "pop", "riser", "impact", "ding"] if args.typ == "alle" else [args.typ]
    written = []
    for kind in kinds:
        for v in range(args.varianten):
            seed = None if args.seed is None else args.seed + v
            pitch = args.tonhoehe * (1 + 0.06 * v * (-1) ** v) if args.varianten > 1 else args.tonhoehe
            data = generate(kind, args.dauer, pitch, seed, args.pegel)
            suffix = f"_{v + 1:02d}" if args.varianten > 1 else ""
            name = args.name if (args.name and len(kinds) == 1 and args.varianten == 1) else f"sfx_{kind}{suffix}.wav"
            written.append(write_wav(out_dir / name, data, SR))
    for p in written:
        print(f"geschrieben: {p}")
    print("Hinweis: selbst synthetisiert, keine Lizenzangabe in lizenzen.md nötig.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("sfx", help="Tool 4: Whoosh/Klick/Pop/Riser/Impact/Ding als WAV synthetisieren")
    p.add_argument("typ", choices=sorted(set(SOUNDS)) + ["alle"], help="Art des Sounds oder 'alle'")
    p.add_argument("--dauer", type=float, help="Länge in Sekunden (Standard je nach Typ)")
    p.add_argument("--tonhoehe", type=float, default=1.0, help="Tonhöhen-Faktor, z. B. 0.8 tiefer, 1.3 höher")
    p.add_argument("--varianten", type=int, default=1, help="Anzahl leicht unterschiedlicher Varianten")
    p.add_argument("--seed", type=int, help="Zufalls-Seed für reproduzierbare Ergebnisse")
    p.add_argument("--pegel", type=float, default=-1.0, help="Spitzenpegel in dBFS (Standard -1)")
    p.add_argument("--ordner", default="03_Audio/sfx", help="Zielordner (Standard: 03_Audio/sfx)")
    p.add_argument("--name", help="Dateiname (nur bei einem Sound und einer Variante)")
    p.set_defaults(func=main)
