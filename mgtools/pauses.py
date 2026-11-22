"""Tool 2 – Pausen-Kürzer: lange Sprechpausen kürzen und Wort-Timestamps neu berechnen (Phase 3.3/3.4)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .common import DEFAULT_SR, ToolError, load_audio, load_words, read_json, save_audio, write_json


# ---------------------------------------------------------------- Pausen finden

def pauses_from_words(words: list[dict], duration: float, max_pause: float, target: float,
                      edges: bool = True) -> list[tuple[float, float]]:
    """Schnitte (start, ende) aus Lücken zwischen Wörtern berechnen.

    Von jeder Lücke > ``max_pause`` bleibt ``target`` Sekunden stehen (je zur Hälfte
    nach dem letzten und vor dem nächsten Wort).
    """
    cuts = []
    bounds = []
    if edges and words:
        bounds.append((0.0, words[0]["start"], "anfang"))
    for a, b in zip(words, words[1:]):
        bounds.append((a["end"], b["start"], "mitte"))
    if edges and words:
        bounds.append((words[-1]["end"], duration, "ende"))
    for gap_start, gap_end, kind in bounds:
        gap = gap_end - gap_start
        if gap <= max_pause:
            continue
        if kind == "anfang":
            cut = (0.0, gap_end - target)
        elif kind == "ende":
            cut = (gap_start + target, duration)
        else:
            cut = (gap_start + target / 2, gap_end - target / 2)
        if cut[1] - cut[0] > 0.005:
            cuts.append((round(cut[0], 4), round(cut[1], 4)))
    return cuts


def pauses_from_audio(samples: np.ndarray, sr: int, max_pause: float, target: float,
                      threshold_db: float = -40.0, frame_ms: float = 10.0) -> list[tuple[float, float]]:
    """Schnitte aus stillen Abschnitten im Audio selbst (RMS unter Schwellwert)."""
    if samples.size == 0:
        return []
    hop = max(1, int(sr * frame_ms / 1000))
    n = len(samples) // hop
    if n == 0:
        return []
    frames = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    peak = max(float(np.max(np.abs(samples))), 1e-9)
    db = 20 * np.log10(rms / peak)
    silent = db < threshold_db
    cuts = []
    i = 0
    duration = len(samples) / sr
    while i < n:
        if not silent[i]:
            i += 1
            continue
        j = i
        while j < n and silent[j]:
            j += 1
        start, end = i * hop / sr, min(j * hop / sr, duration)
        if j >= n:
            end = duration
        gap = end - start
        if gap > max_pause:
            if i == 0:
                cut = (0.0, end - target)
            elif j >= n:
                cut = (start + target, duration)
            else:
                cut = (start + target / 2, end - target / 2)
            if cut[1] - cut[0] > 0.005:
                cuts.append((round(cut[0], 4), round(cut[1], 4)))
        i = j
    return cuts


# ---------------------------------------------------------------- Schneiden & Umrechnen

def apply_cuts(samples: np.ndarray, sr: int, cuts: list[tuple[float, float]],
               fade_ms: float = 8.0) -> np.ndarray:
    """Bereiche entfernen; an jeder Schnittstelle kurze Blende gegen Knackser."""
    if not cuts:
        return samples.copy()
    fade = max(1, int(sr * fade_ms / 1000))
    pieces = []
    pos = 0
    for start, end in sorted(cuts):
        s, e = int(round(start * sr)), int(round(end * sr))
        pieces.append(samples[pos:s].copy())
        pos = e
    pieces.append(samples[pos:].copy())
    for k, piece in enumerate(pieces):
        f = min(fade, len(piece) // 2)
        if f <= 0:
            continue
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        if k > 0:
            piece[:f] *= ramp
        if k < len(pieces) - 1:
            piece[-f:] *= ramp[::-1]
    return np.concatenate(pieces) if pieces else samples[:0]


def remap_time(t: float, cuts: list[tuple[float, float]]) -> float:
    """Zeitpunkt im Original -> Zeitpunkt im gekürzten Audio."""
    removed = 0.0
    for start, end in sorted(cuts):
        if t >= end:
            removed += end - start
        elif t > start:  # liegt im entfernten Bereich -> auf Schnittkante setzen
            removed += t - start
            break
        else:
            break
    return round(t - removed, 4)


def remap_words(words: list[dict], cuts: list[tuple[float, float]]) -> list[dict]:
    out = []
    for w in words:
        nw = dict(w)
        nw["start"] = remap_time(w["start"], cuts)
        nw["end"] = remap_time(w["end"], cuts)
        out.append(nw)
    return out


def load_cuts(path: str) -> list[tuple[float, float]]:
    data = read_json(path)
    items = data["schnitte"] if isinstance(data, dict) else data
    return [(float(c["start"]), float(c["ende"])) for c in items]


# ---------------------------------------------------------------- CLI

def main(args) -> int:
    if args.nur_timing:
        if not args.timing or not args.schnittliste_ein:
            raise ToolError("--nur-timing braucht --timing und --schnittliste-ein.")
        cuts = load_cuts(args.schnittliste_ein)
        words = load_words(args.timing)
        new = remap_words(words, cuts)
        write_json(args.timing_aus, {"words": new})
        print(f"{len(new)} Wörter umgerechnet -> {args.timing_aus}")
        return 0

    if not args.audio:
        raise ToolError("Bitte Audiodatei angeben (z. B. 03_Audio/voice_raw.mp3).")
    sr = DEFAULT_SR
    samples = load_audio(args.audio, sr)
    duration = len(samples) / sr
    words = load_words(args.timing) if args.timing else None

    if words is not None and not args.aus_audio:
        cuts = pauses_from_words(words, duration, args.max_pause, args.ziel, edges=not args.raender_behalten)
        method = "wort-timestamps"
    else:
        cuts = pauses_from_audio(samples, sr, args.max_pause, args.ziel, args.schwelle_db)
        method = "stille-erkennung"

    out = apply_cuts(samples, sr, cuts)
    save_audio(args.aus, out, sr)
    removed = sum(e - s for s, e in cuts)
    cut_list = {
        "quelle": str(args.audio), "methode": method, "max_pause": args.max_pause, "ziel": args.ziel,
        "dauer_vorher": round(duration, 3), "dauer_nachher": round(len(out) / sr, 3),
        "entfernt_sekunden": round(removed, 3),
        "schnitte": [{"start": s, "ende": e, "dauer": round(e - s, 4)} for s, e in cuts],
    }
    write_json(args.schnittliste, cut_list)
    print(f"{len(cuts)} Pausen gekürzt ({method}), {removed:.2f} s entfernt: "
          f"{duration:.2f} s -> {len(out) / sr:.2f} s")
    print(f"Audio: {args.aus}\nSchnittliste: {args.schnittliste}")
    if words is not None:
        new = remap_words(words, cuts)
        write_json(args.timing_aus, {"words": new})
        print(f"Timing neu berechnet: {args.timing_aus} ({len(new)} Wörter)")
        if new:
            picks = [new[0], new[len(new) // 2], new[-1]]
            print("Stichprobe zum Gegenhören: " + "; ".join(
                f"'{w['word']}' @ {w['start']:.2f}s" for w in picks))
    return 0


def register(sub) -> None:
    p = sub.add_parser("pausen", help="Tool 2: lange Sprechpausen kürzen und timing.json neu berechnen")
    p.add_argument("audio", nargs="?", help="Eingangs-Audio, z. B. 03_Audio/voice_raw.mp3")
    p.add_argument("--timing", help="Wort-/Zeichen-Timing, z. B. 03_Audio/timing_raw.json")
    p.add_argument("--aus", default="03_Audio/voice.mp3", help="gekürztes Audio (Standard: 03_Audio/voice.mp3)")
    p.add_argument("--timing-aus", default="03_Audio/timing.json", help="neues Timing (Standard: 03_Audio/timing.json)")
    p.add_argument("--schnittliste", default="03_Audio/schnittliste.json", help="Liste der Schnitte")
    p.add_argument("--max-pause", type=float, default=0.4, help="Pausen länger als das werden gekürzt (s, Standard 0.4)")
    p.add_argument("--ziel", type=float, default=0.25, help="Restlänge einer gekürzten Pause (s, Standard 0.25)")
    p.add_argument("--aus-audio", action="store_true", help="Pausen per Stille-Erkennung statt aus dem Timing finden")
    p.add_argument("--schwelle-db", type=float, default=-40.0, help="Stille-Schwelle relativ zum Peak (Standard -40 dB)")
    p.add_argument("--raender-behalten", action="store_true", help="Stille am Anfang/Ende nicht kürzen")
    p.add_argument("--nur-timing", action="store_true", help="kein Audio schneiden, nur Timing mit --schnittliste-ein umrechnen")
    p.add_argument("--schnittliste-ein", help="vorhandene Schnittliste für --nur-timing")
    p.set_defaults(func=main)
