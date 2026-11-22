import json
import subprocess
from pathlib import Path

import pytest

from mgtools.brand import check_code, parse_brand
from mgtools.checkpoint import build_report, git_commit, parse_status, phase_times, update_status
from mgtools.cli import main as cli
from mgtools.pronounce import convert, load_dictionary
from mgtools.setup_project import create_project


# ---------------------------------------------------------------- Checkpoint / Report

def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    create_project(root, git_init=True)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    return root


def test_update_status_sections(project):
    p = project / "STATUS.md"
    update_status(p, phase="Phase 3: Audio", done=["Skript fertig", "TTS erzeugt"], next_step="Pausen kürzen",
                  questions=["Welche Stimme?", "Musik ja/nein?"], versions=["remotion: 4.0.1"])
    update_status(p, done=["Pausen gekürzt"], resolved=["Stimme"], versions=["remotion: 4.0.2"])
    sec = parse_status(p.read_text(encoding="utf-8"))
    assert sec["Aktuelle Phase"] == ["Phase 3: Audio"]
    assert sec["Erledigt"][-3:] == ["- Skript fertig", "- TTS erzeugt", "- Pausen gekürzt"]
    assert sec["Nächster Schritt"] == ["- Pausen kürzen"]
    assert sec["Offene Fragen"] == ["- Musik ja/nein?"]
    assert "- remotion: 4.0.2" in sec["Tool-Versionen"] and "- remotion: 4.0.1" not in sec["Tool-Versionen"]


def test_cli_status_commit(project):
    assert cli(["status", "--projekt", str(project), "--phase", "Phase 0", "--commit", "Phase 0: Setup"]) == 0
    log = subprocess.run(["git", "log", "--format=%s"], cwd=project, capture_output=True, text=True).stdout
    assert "Phase 0: Setup" in log
    assert git_commit(project, "leer") == "nichts zu committen"


def test_status_without_git(tmp_path):
    (tmp_path / "STATUS.md").write_text("# STATUS\n", encoding="utf-8")
    assert cli(["status", "--projekt", str(tmp_path), "--commit", "x"]) == 2


def test_phase_times():
    from datetime import datetime, timedelta
    t0 = datetime(2026, 1, 1, 10, 0)
    commits = [{"zeit": t0, "nachricht": "Phase 0: Setup"},
               {"zeit": t0 + timedelta(minutes=30), "nachricht": "Phase 1: Brand"},
               {"zeit": t0 + timedelta(minutes=50), "nachricht": "Phase 1: Stack"},
               {"zeit": t0 + timedelta(hours=8), "nachricht": "Phase 3: Audio"}]
    times = phase_times(commits)
    assert times["Phase 1"] == 50 and times["Phase 3"] == 0


def test_report(project):
    cli(["status", "--projekt", str(project), "--commit", "Phase 0: Setup"])
    (project / "03_Audio" / "credits_log.json").write_text(json.dumps(
        [{"dienst": "ElevenLabs TTS", "menge": 1200, "einheit": "Zeichen"},
         {"dienst": "ElevenLabs TTS", "menge": 300, "einheit": "Zeichen"}]))
    assert cli(["report", "--projekt", str(project), "--tokens", "800k", "--kosten", "3 €"]) == 0
    text = (project / "REPORT.md").read_text(encoding="utf-8")
    assert "800k" in text and "ElevenLabs TTS (Zeichen): 1500" in text and "Phase 0" in text
    assert "ffmpeg" in text
    # Learnings bleiben bei erneutem Erzeugen erhalten
    (project / "REPORT.md").write_text(text.replace("- (bitte eintragen)", "- Easing-Preset X übernehmen"), encoding="utf-8")
    assert "Easing-Preset X" in build_report(project)


# ---------------------------------------------------------------- Aussprache

@pytest.fixture(scope="module")
def dic():
    return load_dictionary()


def test_convert_terms(dic):
    out, stats = convert("Mit Claude Code und Remotion bauen wir Motion Graphics für YouTube.", dic)
    assert out == "Mit Klohd Koud und Rimouschen bauen wir Mouschen Gräfiks für Jutjub."
    assert stats["Claude Code"] == 1


def test_convert_case_and_punctuation(dic):
    out, _ = convert("Der workflow, die Tools! (Update)", dic)
    assert out == "Der Wörkflou, die Tuhls! (Apdäit)"


def test_convert_acronyms(dic):
    out, stats = convert("Die API liefert JSON, die KI hilft, die NASA staunt, die EU auch.", dic)
    assert "Äi Pie Ai" in out and "Dschäisen" in out
    assert "Ka I" in out  # deutsche Abkürzung deutsch buchstabiert
    assert "Enn Äi Ess Äi" in out  # unbekannt -> englisch
    assert "E U" in out
    assert convert("Das ist KEIN Tutorial, NUR JETZT.", dic)[0] == "Das ist KEIN Tutorial, NUR JETZT."
    out2, _ = convert("Die NASA staunt.", dic, acronyms="behalten")
    assert out2 == "Die NASA staunt."
    out3, _ = convert("Die NASA staunt.", dic, acronyms="de")
    assert "Enn A Ess A" in out3


def test_convert_no_partial_matches(dic):
    out, _ = convert("Toolbox und Codex bleiben, Teamwork auch.", dic)
    assert out == "Toolbox und Codex bleiben, Teamwork auch."


def test_user_dictionary(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"Kinetic Type": "Kinettick Taip"}), encoding="utf-8")
    d = load_dictionary([tmp_path / "a.json"])
    assert convert("Kinetic Type wirkt.", d)[0] == "Kinettick Taip wirkt."


def test_cli_aussprache_file_and_json(tmp_path, capsys):
    (tmp_path / "skript.txt").write_text("Das Feature ist live.", encoding="utf-8")
    assert cli(["aussprache", str(tmp_path / "skript.txt")]) == 0
    assert (tmp_path / "skript_sprecher.txt").read_text(encoding="utf-8") == "Das Fietscher ist live."
    (tmp_path / "de.json").write_text(json.dumps({"titel": "Neues Update", "liste": ["AI Tools"]}), encoding="utf-8")
    assert cli(["aussprache", str(tmp_path / "de.json"), "--aus", str(tmp_path / "o.json")]) == 0
    assert json.loads((tmp_path / "o.json").read_text(encoding="utf-8")) == {"titel": "Neues Apdäit", "liste": ["Äi Ai Tuhls"]}
    assert cli(["aussprache", "--text", "Ein Prompt"]) == 0


# ---------------------------------------------------------------- Brand

BRAND = """# Brand File

## Farben
- Primär: #0F172A (Nachtblau)
- Akzent: `#22D3EE`
- Hintergrund: #F8FAFC
- Kein Standard-Orange (#FFA500) verwenden!

## Typografie
- Headline: Space Grotesk (700)
- Fließtext: Inter, 400
- Code: `JetBrains Mono`

## Verbote
- Keine Farbverläufe in #FF00FF
"""


def test_parse_brand(tmp_path):
    (tmp_path / "brand.md").write_text(BRAND, encoding="utf-8")
    b = parse_brand(tmp_path / "brand.md")
    assert b["farben"] == ["#0f172a", "#22d3ee", "#f8fafc"]
    assert b["verboten"] == ["#ff00ff", "#ffa500"]
    assert set(b["fonts"]) == {"Space Grotesk", "Inter", "JetBrains Mono"}


def test_check_code(tmp_path):
    (tmp_path / "brand.md").write_text(BRAND, encoding="utf-8")
    code = tmp_path / "code"
    (code / "src").mkdir(parents=True)
    (code / "node_modules" / "x").mkdir(parents=True)
    (code / "node_modules" / "x" / "a.js").write_text("color: '#123456'", encoding="utf-8")
    (code / "src" / "Scene.tsx").write_text(
        "const bg = '#0F172A';\n"
        "const accent = \"#22d3ee\";\n"
        "const bad = '#FFA500';\n"
        "style={{color: 'rgb(255, 0, 0)', fontFamily: 'Comic Sans MS'}}\n"
        "style={{fontFamily: \"Inter, sans-serif\"}}\n"
        "import {loadFont} from '@remotion/google-fonts/Roboto';\n"
        "const white = '#fff'; const near = '#0F172B';\n"
        "<div style={{color: 'orange'}} />\n"
        "const url = 'page#section'; const id = '#main-title';\n", encoding="utf-8")
    (code / "src" / "style.css").write_text("h1 { font-family: 'Space Grotesk', sans-serif; color: hsl(0, 0%, 100%); }\n", encoding="utf-8")
    b = parse_brand(tmp_path / "brand.md")
    f = check_code(code, b)
    got = {(x["zeile"], x["wert"]) for x in f}
    assert (3, "#FFA500") in got
    assert any(x["zeile"] == 4 and x["art"] == "farbe" for x in f)
    assert (4, "Comic Sans MS") in got
    assert (6, "Roboto") in got
    assert (7, "#0F172B") in got
    assert (8, "orange") in got
    assert not any(x["zeile"] in (1, 2, 5, 9) for x in f)
    assert not any(x["datei"].startswith("node_modules") for x in f)
    assert not any(x["datei"].endswith("style.css") for x in f)
    tol = check_code(code, b, tolerance=3)
    assert not any(x["wert"] == "#0F172B" for x in tol)
    strict = check_code(code, b, allow_neutral=False)
    assert any(x["wert"] == "#fff" for x in strict)


def test_cli_brand(tmp_path, capsys):
    (tmp_path / "02_Brand").mkdir()
    (tmp_path / "02_Brand" / "brand.md").write_text(BRAND, encoding="utf-8")
    (tmp_path / "05_Code").mkdir()
    (tmp_path / "05_Code" / "a.css").write_text("a { color: #22D3EE; }", encoding="utf-8")
    assert cli(["brand", "--brand", str(tmp_path / "02_Brand/brand.md"), "--code", str(tmp_path / "05_Code")]) == 0
    (tmp_path / "05_Code" / "b.css").write_text("a { color: #ff0000; }", encoding="utf-8")
    assert cli(["brand", "--brand", str(tmp_path / "02_Brand/brand.md"), "--code", str(tmp_path / "05_Code"),
                "--json"]) == 1
    assert '"#ff0000"' in capsys.readouterr().out
