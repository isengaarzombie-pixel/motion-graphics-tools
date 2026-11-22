from pathlib import Path
import builtins
import sys

import pytest
from PIL import Image

from mgtools import cutout
from mgtools.cli import main as cli
from mgtools.common import ToolError
from mgtools.licenses import add_entry, check, read_entries


def fake_remover(img):
    """Weiße Pixel transparent machen (Ersatz für rembg)."""
    import numpy as np

    arr = np.array(img.convert("RGBA"))
    white = (arr[..., :3] > 235).all(axis=-1)  # tolerant wegen JPEG-Artefakten
    arr[..., 3] = np.where(white, 0, 255)
    return Image.fromarray(arr, "RGBA")


def _img(path, size=(60, 40), quality=False):
    im = Image.new("RGB", size, "white")
    for x in range(20, 40):
        for y in range(10, 30):
            im.putpixel((x, y), (200, 30, 30))
    im.save(path, **({"quality": 100, "subsampling": 0} if quality else {}))


def test_process_folder_sort_trim_skip(tmp_path):
    src = tmp_path / "roh"
    src.mkdir()
    _img(src / "char_bob.jpg", quality=True)
    _img(src / "icon_stern.png")
    _img(src / "hintergrund.png")
    (src / "notiz.txt").write_text("x", encoding="utf-8")
    dst = tmp_path / "frei"
    res = cutout.process_folder(src, dst, fake_remover, sort=True, trim=True, padding=2)
    assert [r["status"] for r in res] == ["ok"] * 3
    out = Image.open(dst / "char" / "char_bob.png")
    assert out.mode == "RGBA" and out.size == (24, 24)
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((12, 12))[3] == 255
    assert (dst / "icon" / "icon_stern.png").exists() and (dst / "sonstiges" / "hintergrund.png").exists()
    again = cutout.process_folder(src, dst, fake_remover, sort=True)
    assert all(r["status"].startswith("übersprungen") for r in again)


def test_process_folder_error_does_not_stop(tmp_path):
    src = tmp_path / "roh"
    src.mkdir()
    _img(src / "a.png")
    (src / "kaputt.png").write_bytes(b"keinbild")
    res = cutout.process_folder(src, tmp_path / "o", fake_remover)
    status = {Path(r["datei"]).name: r["status"] for r in res}
    assert status["a.png"] == "ok" and status["kaputt.png"].startswith("fehler")


def test_move_originals(tmp_path):
    src = tmp_path / "roh"
    src.mkdir()
    _img(src / "a.png")
    cutout.process_folder(src, tmp_path / "o", fake_remover, move_originals=tmp_path / "orig")
    assert not (src / "a.png").exists() and (tmp_path / "orig" / "a.png").exists()


def test_cli_freistellen_with_mock(tmp_path, monkeypatch):
    src = tmp_path / "roh"
    src.mkdir()
    _img(src / "x.png")
    monkeypatch.setattr(cutout, "rembg_remover", lambda model: fake_remover)
    assert cli(["freistellen", str(src), "--ausgang", str(tmp_path / "f")]) == 0
    assert (tmp_path / "f" / "x.png").exists()


def test_rembg_missing_message(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "rembg":
            raise ImportError("nope")
        return real_import(name, *a, **k)

    monkeypatch.setitem(sys.modules, "rembg", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ToolError, match="pip install"):
        cutout.rembg_remover()


def test_license_add_and_read(tmp_path):
    lic = tmp_path / "lizenzen.md"
    hints = add_entry(lic, "04_Assets/foto.jpg", "https://archive.org/details/x", "Max | Muster", "CC0")
    assert any("Archive.org" in h for h in hints)
    e = read_entries(lic)
    assert e[0]["Urheber"] == "Max | Muster" and e[0]["Lizenz"] == "CC0" and e[0]["Abrufdatum"]
    with pytest.raises(ToolError, match="schon"):
        add_entry(lic, "04_Assets/foto.jpg", "https://x.org", "a", "CC0")


def test_license_forbidden_and_missing_license(tmp_path):
    lic = tmp_path / "lizenzen.md"
    with pytest.raises(ToolError, match="Referenz"):
        add_entry(lic, "a.png", "https://www.pinterest.com/pin/1", "?", "unbekannt")
    with pytest.raises(ToolError, match="Lizenz"):
        add_entry(lic, "a.png", "https://pixabay.com/x", "a", "")


def test_license_check(tmp_path):
    (tmp_path / "04_Assets" / "frei").mkdir(parents=True)
    (tmp_path / "04_Assets" / ".gitkeep").touch()
    (tmp_path / "04_Assets" / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "04_Assets" / "frei" / "foto.png").write_bytes(b"x")
    (tmp_path / "04_Assets" / "clip.mp4").write_bytes(b"x")
    lic = tmp_path / "lizenzen.md"
    add_entry(lic, "04_Assets/logo.svg", "", "ich", "eigen")
    add_entry(lic, "foto.png", "https://unsplash.com/p/1", "Ana", "Unsplash License")
    res = check(tmp_path, lic, ["04_Assets"], [".gitkeep"])
    assert res["ohne_nachweis"] == ["04_Assets/clip.mp4"]
    assert res["unvollstaendig"] == []
    assert cli(["lizenz", "pruefen", "--projekt", str(tmp_path)]) == 1
    assert cli(["lizenz", "add", "04_Assets/clip.mp4", "--quelle", "https://pexels.com/v/2", "--urheber", "B",
                "--lizenz", "Pexels License", "--projekt", str(tmp_path)]) == 0
    assert cli(["lizenz", "pruefen", "--projekt", str(tmp_path)]) == 0
    assert cli(["lizenz", "liste", "--projekt", str(tmp_path)]) == 0
