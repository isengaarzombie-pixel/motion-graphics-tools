"""Tool 5 – Asset-Freisteller: Hintergründe im Stapel mit rembg entfernen und einsortieren (Phase 4.2)."""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from .common import ToolError

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def rembg_remover(model: str = "u2net") -> Callable[[Image.Image], Image.Image]:
    try:
        from rembg import new_session, remove  # type: ignore
    except ImportError as exc:  # pragma: no cover - hängt von Installation ab
        raise ToolError(
            "rembg ist nicht installiert. In der .venv ausführen: pip install \"rembg[cpu]\" "
            "(oder: pip install \"motion-graphics-tools[freisteller]\")."
        ) from exc
    session = new_session(model)

    def _remove(img: Image.Image) -> Image.Image:
        out = remove(img, session=session)
        if isinstance(out, (bytes, bytearray)):
            out = Image.open(io.BytesIO(out))
        return out.convert("RGBA")

    return _remove


def trim_transparent(img: Image.Image, padding: int = 0) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return img
    l, t, r, b = bbox
    l, t = max(0, l - padding), max(0, t - padding)
    r, b = min(img.width, r + padding), min(img.height, b + padding)
    return img.crop((l, t, r, b))


def category_of(path: Path) -> str:
    stem = path.stem
    return stem.split("_", 1)[0].lower() if "_" in stem else "sonstiges"


def process_folder(src: Path, dst: Path, remover: Callable[[Image.Image], Image.Image],
                   sort: bool = False, trim: bool = False, padding: int = 0, overwrite: bool = False,
                   move_originals: Path | None = None) -> list[dict]:
    if not src.is_dir():
        raise ToolError(f"Eingangsordner nicht gefunden: {src}")
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    results = []
    for f in files:
        target_dir = dst / category_of(f) if sort else dst
        target = target_dir / (f.stem + ".png")
        if target.exists() and not overwrite:
            results.append({"datei": str(f), "ziel": str(target), "status": "übersprungen (existiert)"})
            continue
        try:
            with Image.open(f) as im:
                im.load()
                out = remover(im.convert("RGBA"))
            if trim:
                out = trim_transparent(out, padding)
            target_dir.mkdir(parents=True, exist_ok=True)
            out.save(target, "PNG")
            if move_originals is not None:
                move_originals.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(move_originals / f.name))
            results.append({"datei": str(f), "ziel": str(target), "status": "ok",
                            "groesse": f"{out.width}x{out.height}"})
        except Exception as exc:  # einzelnes Bild darf den Stapel nicht abbrechen
            results.append({"datei": str(f), "ziel": str(target), "status": f"fehler: {exc}"})
    return results


def main(args) -> int:
    remover = rembg_remover(args.modell)
    res = process_folder(Path(args.eingang), Path(args.ausgang), remover, sort=args.sortieren,
                         trim=args.zuschneiden, padding=args.rand, overwrite=args.neu,
                         move_originals=Path(args.originale) if args.originale else None)
    if not res:
        print(f"Keine Bilder in {args.eingang} gefunden.")
        return 0
    for r in res:
        print(f"[{r['status']}] {r['datei']} -> {r['ziel']}")
    errors = [r for r in res if r["status"].startswith("fehler")]
    print(f"{len(res) - len(errors)} von {len(res)} verarbeitet.")
    return 1 if errors else 0


def register(sub) -> None:
    p = sub.add_parser("freistellen", help="Tool 5: Hintergründe per rembg im Stapel entfernen und einsortieren")
    p.add_argument("eingang", nargs="?", default="04_Assets/roh", help="Ordner mit Bildern (Standard: 04_Assets/roh)")
    p.add_argument("--ausgang", default="04_Assets/freigestellt", help="Zielordner (Standard: 04_Assets/freigestellt)")
    p.add_argument("--sortieren", action="store_true", help="nach Präfix vor '_' in Unterordner sortieren (char_bob.png -> char/)")
    p.add_argument("--zuschneiden", action="store_true", help="transparenten Rand abschneiden")
    p.add_argument("--rand", type=int, default=0, help="Pixel Rand beim Zuschneiden")
    p.add_argument("--modell", default="u2net", help="rembg-Modell (u2net, isnet-general-use, birefnet-general …)")
    p.add_argument("--neu", action="store_true", help="vorhandene Ergebnisse überschreiben")
    p.add_argument("--originale", help="Originale nach Erfolg in diesen Ordner verschieben")
    p.set_defaults(func=main)
