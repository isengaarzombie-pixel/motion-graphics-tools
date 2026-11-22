"""Gemeinsame Hilfsfunktionen: FFmpeg-Aufrufe, Audio laden/schreiben, Timing-Formate, JSON."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SR = 44100


class ToolError(RuntimeError):
    """Fehler, der dem Nutzer/LLM als klare Meldung angezeigt wird (ohne Traceback)."""


# ---------------------------------------------------------------- JSON / Dateien

def read_json(path: str | os.PathLike) -> Any:
    p = Path(path)
    if not p.exists():
        raise ToolError(f"Datei nicht gefunden: {p}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | os.PathLike, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Minimaler .env-Leser: setzt nur Variablen, die noch nicht gesetzt sind."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# ---------------------------------------------------------------- FFmpeg

def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolError(
            f"'{name}' wurde nicht gefunden. Bitte installieren (z. B. winget install ffmpeg / "
            f"brew install ffmpeg / sudo apt install ffmpeg) und Terminal neu starten."
        )
    return path


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, input=input_bytes, capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-2000:]
        raise ToolError(f"Befehl fehlgeschlagen: {' '.join(cmd[:3])} …\n{err}")
    return proc


def load_audio(path: str | os.PathLike, sr: int = DEFAULT_SR) -> np.ndarray:
    """Beliebige Audio-/Videodatei per FFmpeg als Mono-float32-Array laden."""
    ffmpeg = require_binary("ffmpeg")
    if not Path(path).exists():
        raise ToolError(f"Audiodatei nicht gefunden: {path}")
    proc = run([ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                "-f", "f32le", "-"])
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def save_audio(path: str | os.PathLike, samples: np.ndarray, sr: int = DEFAULT_SR) -> Path:
    """Mono-float32-Array speichern. Format ergibt sich aus der Endung (.wav, .mp3, …)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    if p.suffix.lower() == ".wav":
        write_wav(p, data, sr)
        return p
    ffmpeg = require_binary("ffmpeg")
    extra = ["-b:a", "192k"] if p.suffix.lower() == ".mp3" else []
    run([ffmpeg, "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         *extra, str(p)], input_bytes=data.tobytes())
    return p


def write_wav(path: str | os.PathLike, samples: np.ndarray, sr: int = DEFAULT_SR) -> Path:
    """16-bit-PCM-WAV ohne FFmpeg schreiben (Mono oder Stereo: shape (n,) bzw. (n, 2))."""
    import wave

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    channels = 1 if data.ndim == 1 else data.shape[1]
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return p


def read_wav(path: str | os.PathLike) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767
    if ch > 1:
        data = data.reshape(-1, ch)
    return data, sr


def ffprobe(path: str | os.PathLike) -> dict:
    probe = require_binary("ffprobe")
    if not Path(path).exists():
        raise ToolError(f"Datei nicht gefunden: {path}")
    proc = run([probe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                str(path)])
    return json.loads(proc.stdout)


# ---------------------------------------------------------------- Timing-Formate

def words_from_alignment(alignment: dict) -> list[dict]:
    """ElevenLabs-Alignment (zeichengenau) in Wörter umwandeln.

    Erwartet die Felder ``characters``, ``character_start_times_seconds`` und
    ``character_end_times_seconds`` (so liefert sie der Endpoint "with timestamps").
    """
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    words: list[dict] = []
    cur, cur_start, cur_end = "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"word": cur, "start": round(cur_start, 4), "end": round(cur_end, 4)})
            cur, cur_start, cur_end = "", None, None
            continue
        if not cur:
            cur_start = s
        cur += ch
        cur_end = e
    if cur:
        words.append({"word": cur, "start": round(cur_start, 4), "end": round(cur_end, 4)})
    return _attach_punctuation(words)


def _attach_punctuation(words: list[dict]) -> list[dict]:
    """Reine Satzzeichen-Tokens ("...", "–") sind keine Wörter: Text ans vorige Wort hängen, Zeiten nicht.

    Sonst zerlegt z. B. "Video. ... Zuerst" eine lange Pause in zwei kurze Lücken, die ``pausen`` übersieht.
    """
    out: list[dict] = []
    prefix = ""
    for w in words:
        if not any(ch.isalnum() for ch in w["word"]):
            if out:
                out[-1]["word"] += " " + w["word"]
            else:
                prefix += w["word"] + " "
            continue
        if prefix:
            w = {**w, "word": prefix + w["word"]}
            prefix = ""
        out.append(w)
    return out


def load_words(path: str | os.PathLike) -> list[dict]:
    """Wort-Timings aus verschiedenen Formaten laden.

    Unterstützt:
    * ``{"words": [{"word"|"text", "start", "end"}, …]}`` (eigenes Format, Scribe-ähnlich)
    * eine reine Liste solcher Wörter
    * ElevenLabs-TTS-Antwort mit ``alignment`` bzw. ``normalized_alignment``
    * ein reines Alignment-Objekt mit ``characters``-Feld
    """
    data = read_json(path)
    return normalize_words(data)


def normalize_words(data: Any) -> list[dict]:
    if isinstance(data, dict):
        if "words" in data:
            data = data["words"]
        elif "alignment" in data and data["alignment"]:
            return words_from_alignment(data["alignment"])
        elif "normalized_alignment" in data and data["normalized_alignment"]:
            return words_from_alignment(data["normalized_alignment"])
        elif "characters" in data:
            return words_from_alignment(data)
        else:
            raise ToolError("Unbekanntes Timing-Format (erwartet 'words' oder 'alignment').")
    out = []
    for w in data:
        if w.get("type") in ("spacing", "audio_event"):  # Scribe-Ausgabe
            continue
        text = w.get("word", w.get("text", "")).strip()
        if not text:
            continue
        out.append({"word": text, "start": float(w["start"]), "end": float(w["end"])})
    out.sort(key=lambda w: w["start"])
    return _attach_punctuation(out)
