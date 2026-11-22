import json

import numpy as np
import pytest

from mgtools.cli import main as cli
from mgtools.common import ToolError, read_wav
from mgtools.sfx import SOUNDS, generate
from mgtools.timetable import build_scenes, split_sentences, timetable_markdown

WORDS = [
    {"word": "Willkommen", "start": 0.0, "end": 0.5}, {"word": "zurück.", "start": 0.55, "end": 1.0},
    {"word": "Heute", "start": 1.3, "end": 1.6}, {"word": "bauen", "start": 1.65, "end": 2.0},
    {"word": "wir", "start": 2.05, "end": 2.2}, {"word": "Motion", "start": 2.25, "end": 2.6},
    {"word": "Graphics!", "start": 2.65, "end": 3.2}, {"word": "Los", "start": 3.5, "end": 3.7},
    {"word": "geht's.", "start": 3.75, "end": 4.1},
]


def test_split_sentences():
    assert split_sentences(WORDS) == [0, 2, 7]


def test_build_scenes_sentences_frames():
    d = build_scenes(WORDS, 30)
    s = d["szenen"]
    assert [x["id"] for x in s] == ["szene_01", "szene_02", "szene_03"]
    assert s[0]["startFrame"] == 0 and s[1]["startFrame"] == 39 and s[2]["startFrame"] == 105
    # lückenlos
    assert all(a["endFrame"] == b["startFrame"] for a, b in zip(s, s[1:]))
    assert s[-1]["endFrame"] == d["dauer_frames"] == 138  # (4.1 + 0.5) * 30
    assert sum(x["durationInFrames"] for x in s) == d["dauer_frames"]
    assert s[1]["words"][0]["relFrame"] == 0 and s[1]["words"][1]["frame"] == 49


def test_build_scenes_with_definitions():
    defs = [{"id": "hook", "start": "Heute bauen", "aktion": "Titel fliegt ein", "sfx": "whoosh"},
            {"id": "outro", "start": "los geht's"}]
    d = build_scenes(WORDS, 25, defs, total=5.0)
    ids = [x["id"] for x in d["szenen"]]
    assert ids == ["vorlauf", "hook", "outro"]
    assert d["szenen"][1]["aktion"] == "Titel fliegt ein"
    assert d["dauer_frames"] == 125
    assert build_scenes(WORDS, 30, total=4.2)["dauer_frames"] == 126  # Audiodauer exakt übernommen
    md = timetable_markdown(d)
    assert "| hook |" in md and "Titel fliegt ein" in md and "whoosh" in md


def test_build_scenes_bad_phrase():
    with pytest.raises(ToolError):
        build_scenes(WORDS, 30, [{"id": "a", "start": "gibt es nicht"}])


def test_cli_timetable(tmp_path):
    (tmp_path / "timing.json").write_text(json.dumps({"words": WORDS}), encoding="utf-8")
    assert cli(["timetable", str(tmp_path / "timing.json"), "--fps", "60", "--aus",
                str(tmp_path / "scenes.json"), "--md", str(tmp_path / "tt.md")]) == 0
    d = json.loads((tmp_path / "scenes.json").read_text(encoding="utf-8"))
    assert d["fps"] == 60 and len(d["szenen"]) == 3
    assert (tmp_path / "tt.md").read_text(encoding="utf-8").startswith("# Timetable")


@pytest.mark.parametrize("kind", sorted(set(SOUNDS)))
def test_generate_each_sound(kind):
    y = generate(kind, seed=1)
    assert y.ndim == 2 and y.shape[1] == 2
    assert np.isfinite(y).all()
    peak = np.max(np.abs(y))
    assert abs(20 * np.log10(peak) - (-1.0)) < 0.05


def test_generate_deterministic_and_duration():
    a, b = generate("whoosh", 0.4, seed=7), generate("whoosh", 0.4, seed=7)
    assert np.array_equal(a, b) and len(a) == int(44100 * 0.4)
    with pytest.raises(ToolError):
        generate("laser")
    with pytest.raises(ToolError):
        generate("pop", 100)


def test_whoosh_is_band_limited_and_pans():
    y = generate("whoosh", 0.8, seed=3)
    n = len(y)
    left_first = np.abs(y[: n // 3, 0]).mean() > np.abs(y[: n // 3, 1]).mean()
    right_last = np.abs(y[-n // 3:, 1]).mean() > np.abs(y[-n // 3:, 0]).mean()
    assert left_first and right_last


def test_riser_gets_louder():
    y = generate("riser", 2.0, seed=1)[:, 0]
    q = len(y) // 4
    assert np.abs(y[-q:]).mean() > 4 * np.abs(y[:q]).mean()


def test_cli_sfx_all_and_variants(tmp_path):
    assert cli(["sfx", "alle", "--ordner", str(tmp_path), "--seed", "1"]) == 0
    names = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert names == ["sfx_ding.wav", "sfx_impact.wav", "sfx_klick.wav", "sfx_pop.wav", "sfx_riser.wav", "sfx_whoosh.wav"]
    data, sr = read_wav(tmp_path / "sfx_klick.wav")
    assert sr == 44100 and data.shape[1] == 2
    assert cli(["sfx", "pop", "--varianten", "3", "--ordner", str(tmp_path / "v")]) == 0
    assert len(list((tmp_path / "v").glob("sfx_pop_*.wav"))) == 3
    assert cli(["sfx", "whoosh", "--name", "intro.wav", "--ordner", str(tmp_path)]) == 0
    assert (tmp_path / "intro.wav").exists()
