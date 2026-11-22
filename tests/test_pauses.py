import json

import numpy as np
import pytest

from conftest import SR, make_alignment, needs_ffmpeg, silence, tone
from mgtools.cli import main as cli
from mgtools.common import load_audio, read_wav
from mgtools.pauses import apply_cuts, pauses_from_audio, pauses_from_words, remap_time, remap_words


def test_pauses_from_words(speech):
    _, words, audio = speech
    cuts = pauses_from_words(words, len(audio) / SR, 0.4, 0.25)
    # Anfang 0.3 (nicht > 0.4) bleibt, 1.2-Pause, 0.6-Pause und 0.8-Ende werden gekürzt
    assert len(cuts) == 3
    assert cuts[0] == (1.525, 2.475)
    assert cuts[1] == (3.225, 3.575)
    assert cuts[2] == (4.45, 5.0)


def test_remap_time():
    cuts = [(1.0, 2.0), (3.0, 3.5)]
    assert remap_time(0.5, cuts) == 0.5
    assert remap_time(2.5, cuts) == 1.5
    assert remap_time(4.0, cuts) == 2.5
    assert remap_time(1.5, cuts) == 1.0  # im Schnitt -> Schnittkante


def _onsets(audio, thr=0.05, hop=441):
    n = len(audio) // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    active = rms > thr
    return [i * hop / SR for i in range(1, n) if active[i] and not active[i - 1]] + \
        ([0.0] if active[0] else [])


def test_apply_cuts_and_remap_match_audio(speech):
    _, words, audio = speech
    cuts = pauses_from_words(words, len(audio) / SR, 0.4, 0.25)
    out = apply_cuts(audio, SR, cuts)
    removed = sum(e - s for s, e in cuts)
    assert abs(len(out) / SR - (len(audio) / SR - removed)) < 0.01
    new_words = remap_words(words, cuts)
    onsets = sorted(_onsets(out))
    # jedes neu berechnete Wort beginnt dort, wo im gekürzten Audio wieder Ton einsetzt
    for w in new_words:
        assert min(abs(o - w["start"]) for o in onsets) < 0.02, (w, onsets)


def test_pauses_from_audio_detects_silence(speech):
    _, _, audio = speech
    cuts = pauses_from_audio(audio, SR, 0.4, 0.25)
    assert len(cuts) == 3
    assert abs((cuts[0][1] - cuts[0][0]) - 0.95) < 0.03


@needs_ffmpeg
def test_cli_pausen_with_alignment(speech, tmp_path, capsys):
    path, words, audio = speech
    timing = tmp_path / "timing_raw.json"
    timing.write_text(json.dumps({"alignment": make_alignment(words)}), encoding="utf-8")
    out_audio = tmp_path / "voice.wav"
    rc = cli(["pausen", str(path), "--timing", str(timing), "--aus", str(out_audio),
              "--timing-aus", str(tmp_path / "timing.json"), "--schnittliste", str(tmp_path / "cuts.json")])
    assert rc == 0
    data, sr = read_wav(out_audio)
    assert abs(len(data) / sr - (5.0 - 0.95 - 0.35 - 0.55)) < 0.02
    new = json.loads((tmp_path / "timing.json").read_text())["words"]
    assert [w["word"] for w in new] == ["Hallo", "Welt.", "Das", "funktioniert!"]
    assert abs(new[2]["start"] - 1.65) < 0.01
    cuts = json.loads((tmp_path / "cuts.json").read_text())
    assert cuts["methode"] == "wort-timestamps" and len(cuts["schnitte"]) == 3
    assert "Stichprobe" in capsys.readouterr().out


@needs_ffmpeg
def test_cli_pausen_mp3_and_silence_mode(speech, tmp_path):
    path, _, _ = speech
    out = tmp_path / "voice.mp3"
    assert cli(["pausen", str(path), "--aus-audio", "--aus", str(out),
                "--schnittliste", str(tmp_path / "c.json")]) == 0
    dur = len(load_audio(out)) / SR
    assert abs(dur - 3.15) < 0.1  # mp3 hat etwas Encoder-Padding


def test_cli_nur_timing(speech, tmp_path):
    _, words, _ = speech
    (tmp_path / "t.json").write_text(json.dumps({"words": words}))
    (tmp_path / "c.json").write_text(json.dumps({"schnitte": [{"start": 1.525, "ende": 2.475}]}))
    assert cli(["pausen", "--nur-timing", "--timing", str(tmp_path / "t.json"), "--schnittliste-ein",
                str(tmp_path / "c.json"), "--timing-aus", str(tmp_path / "o.json")]) == 0
    new = json.loads((tmp_path / "o.json").read_text())["words"]
    assert abs(new[2]["start"] - 1.65) < 1e-6


def test_cli_pausen_missing_file(tmp_path, capsys):
    assert cli(["pausen", str(tmp_path / "gibtsnicht.mp3")]) == 2
    assert "nicht gefunden" in capsys.readouterr().err
