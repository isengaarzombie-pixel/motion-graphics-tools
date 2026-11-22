import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from mgtools.common import write_wav

SR = 44100
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")


def tone(dur, freq=440.0, amp=0.5, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(dur, sr=SR):
    return np.zeros(int(dur * sr), dtype=np.float32)


@pytest.fixture
def speech(tmp_path):
    """Künstliche 'Sprache': 4 Wörter (Töne) mit unterschiedlich langen Pausen.

    Layout (s): 0.0–0.3 Stille | W1 0.3–0.8 | 0.1 | W2 0.9–1.4 | 1.2 Pause | W3 2.6–3.1 | 0.6 Pause |
    W4 3.7–4.2 | 0.8 Stille bis 5.0
    """
    parts = [silence(0.3), tone(0.5, 300), silence(0.1), tone(0.5, 400), silence(1.2), tone(0.5, 500),
             silence(0.6), tone(0.5, 600), silence(0.8)]
    audio = np.concatenate(parts)
    path = write_wav(tmp_path / "voice_raw.wav", audio, SR)
    words = [{"word": "Hallo", "start": 0.3, "end": 0.8}, {"word": "Welt.", "start": 0.9, "end": 1.4},
             {"word": "Das", "start": 2.6, "end": 3.1}, {"word": "funktioniert!", "start": 3.7, "end": 4.2}]
    return path, words, audio


def make_alignment(words):
    """Wörter -> ElevenLabs-Zeichen-Alignment."""
    chars, starts, ends = [], [], []
    for i, w in enumerate(words):
        if i:
            chars.append(" ")
            starts.append(words[i - 1]["end"])
            ends.append(w["start"])
        n = len(w["word"])
        step = (w["end"] - w["start"]) / n
        for k, c in enumerate(w["word"]):
            chars.append(c)
            starts.append(round(w["start"] + k * step, 4))
            ends.append(round(w["start"] + (k + 1) * step, 4))
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


def make_video(path: Path, w=1920, h=1080, fps=30, dur=2.0, volume_db=-30.0, audio=True, codec="libx264"):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}:sample_rate=48000",
                "-af", f"volume={volume_db}dB", "-c:a", "aac"]
    cmd += ["-c:v", codec, "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path
