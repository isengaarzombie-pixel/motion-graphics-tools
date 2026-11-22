import json
import os

import numpy as np

from conftest import make_alignment
from mgtools.cli import main as cli
from mgtools.common import load_dotenv, normalize_words, read_wav, words_from_alignment, write_wav
from mgtools.setup_project import FOLDERS, check_tools, create_project


def test_words_from_alignment_roundtrip():
    words = [{"word": "Hallo", "start": 0.1, "end": 0.5}, {"word": "Welt", "start": 0.6, "end": 1.0}]
    out = words_from_alignment(make_alignment(words))
    assert [w["word"] for w in out] == ["Hallo", "Welt"]
    assert out[0]["start"] == 0.1 and abs(out[1]["end"] - 1.0) < 1e-6


def test_normalize_words_formats():
    al = make_alignment([{"word": "A", "start": 0, "end": 0.2}])
    assert normalize_words({"alignment": al})[0]["word"] == "A"
    assert normalize_words({"normalized_alignment": al, "alignment": None})[0]["word"] == "A"
    assert normalize_words(al)[0]["word"] == "A"
    scribe = {"words": [{"text": "Hi", "start": 0, "end": 0.2, "type": "word"},
                        {"text": " ", "start": 0.2, "end": 0.3, "type": "spacing"},
                        {"text": "du", "start": 0.3, "end": 0.5, "type": "word"}]}
    assert [w["word"] for w in normalize_words(scribe)] == ["Hi", "du"]


def test_wav_roundtrip(tmp_path):
    data = np.sin(np.linspace(0, 100, 4410)).astype(np.float32) * 0.5
    write_wav(tmp_path / "a.wav", data, 44100)
    back, sr = read_wav(tmp_path / "a.wav")
    assert sr == 44100 and np.allclose(back, data, atol=1e-3)


def test_load_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("MGT_TEST_KEY", raising=False)
    (tmp_path / ".env").write_text('# Kommentar\nMGT_TEST_KEY="abc"\n', encoding="utf-8")
    load_dotenv(tmp_path / ".env")
    assert os.environ["MGT_TEST_KEY"] == "abc"


def test_create_project_idempotent(tmp_path):
    created = create_project(tmp_path / "p", git_init=True)
    root = tmp_path / "p"
    for f in FOLDERS:
        assert (root / f).is_dir()
    for f in ["STATUS.md", "lizenzen.md", ".gitignore", ".env.example", "05_Code/i18n/de.json"]:
        assert (root / f).exists()
    assert ".env" in (root / ".gitignore").read_text(encoding="utf-8")
    assert (root / ".git").exists()
    (root / "STATUS.md").write_text("eigener Inhalt", encoding="utf-8")
    assert create_project(root) == []
    assert (root / "STATUS.md").read_text(encoding="utf-8") == "eigener Inhalt"
    assert "STATUS.md" in created


def test_check_tools_reports_all():
    res = check_tools()
    names = {r["tool"] for r in res}
    assert {"git", "node", "python", "ffmpeg"} <= names
    py = next(r for r in res if r["tool"] == "python")
    assert py["ok"] and py["version"].startswith("3")


def test_cli_setup(tmp_path, capsys):
    assert cli(["setup", str(tmp_path / "x")]) == 0
    out = capsys.readouterr().out
    assert "Basis-Check" in out and "ffmpeg" in out


def test_cli_help_lists_13_tools(capsys):
    assert cli([]) == 0
    out = capsys.readouterr().out
    for i in range(1, 14):
        assert f"Tool {i}" in out
