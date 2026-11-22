"""Tool 7 – Storyboard-Sheet: Screenshots/Frames zu einer Übersicht mit Safe-Area-Overlay (Phase 5, Phase 7.1)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import ToolError, read_json, require_binary, run

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# Anteile des Bildes, die bei Shorts/Reels von der App-UI überdeckt werden (Richtwerte)
SAFE_AREAS = {
    "shorts": {"unten": 0.20, "rechts": 0.13, "oben": 0.08, "links": 0.04},
    "16:9": {"unten": 0.05, "rechts": 0.05, "oben": 0.05, "links": 0.05},
}


def _font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def overlay_safe_area(img: Image.Image, kind: str) -> Image.Image:
    """Halbtransparente rote Flächen über Bereiche legen, die frei bleiben müssen."""
    if kind not in SAFE_AREAS:
        raise ToolError(f"Unbekannte Safe-Area '{kind}'. Möglich: {', '.join(SAFE_AREAS)}")
    a = SAFE_AREAS[kind]
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = base.size
    red = (255, 0, 0, 130)
    d.rectangle([0, h - int(h * a["unten"]), w, h], fill=red)
    d.rectangle([w - int(w * a["rechts"]), 0, w, h], fill=red)
    d.rectangle([0, 0, w, int(h * a["oben"])], fill=red)
    d.rectangle([0, 0, int(w * a["links"]), h], fill=red)
    # Rahmen der sicheren Zone deutlich markieren (auch auf roten/orangen Bildern sichtbar)
    lw = max(2, w // 200)
    box = [int(w * a["links"]), int(h * a["oben"]), w - int(w * a["rechts"]), h - int(h * a["unten"])]
    d.rectangle(box, outline=(255, 255, 255, 230), width=lw)
    d.rectangle([box[0] + lw, box[1] + lw, box[2] - lw, box[3] - lw], outline=(255, 0, 0, 230), width=lw)
    return Image.alpha_composite(base, layer)


def extract_frames(video: Path, scenes: dict, out_dir: Path, position: float = 0.5) -> list[Path]:
    """Pro Szene ein Standbild aus dem Video holen (Standard: Mitte der Szene)."""
    ffmpeg = require_binary("ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, s in enumerate(scenes["szenen"]):
        t = s["start"] + (s["end"] - s["start"]) * position
        p = out_dir / f"{k + 1:02d}_{s['id']}.png"
        run([ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(p)])
        paths.append(p)
    return paths


def build_sheet(images: list[Path], columns: int = 3, thumb_width: int = 480,
                captions: dict[str, str] | None = None, safe_area: str | None = None,
                title: str | None = None) -> Image.Image:
    if not images:
        raise ToolError("Keine Bilder für das Storyboard gefunden.")
    captions = captions or {}
    thumbs = []
    for p in images:
        with Image.open(p) as im:
            im = im.convert("RGBA")
            if safe_area:
                im = overlay_safe_area(im, safe_area)
            ratio = thumb_width / im.width
            thumbs.append(im.resize((thumb_width, max(1, int(im.height * ratio))), Image.LANCZOS))
    cell_h = max(t.height for t in thumbs)
    pad, label_h = 24, 56
    title_h = 60 if title else 0
    columns = max(1, min(columns, len(thumbs)))
    rows = (len(thumbs) + columns - 1) // columns
    W = columns * thumb_width + (columns + 1) * pad
    H = title_h + rows * (cell_h + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    f_big, f_small = _font(28), _font(16)
    if title:
        d.text((pad, pad // 2 + 8), title, fill=(240, 240, 240), font=f_big)
    for i, (p, t) in enumerate(zip(images, thumbs)):
        r, c = divmod(i, columns)
        x = pad + c * (thumb_width + pad)
        y = title_h + pad + r * (cell_h + label_h + pad)
        sheet.paste(t.convert("RGB"), (x, y))
        d.rectangle([x - 1, y - 1, x + t.width, y + t.height], outline=(70, 70, 80))
        label = f"{i + 1:02d} · {p.stem}"
        d.text((x, y + t.height + 6), label, fill=(230, 230, 230), font=f_small)
        cap = captions.get(p.stem) or next((v for k, v in captions.items() if p.stem.endswith(k)), "")
        if cap:
            cap = cap if len(cap) <= 70 else cap[:67] + "…"
            d.text((x, y + t.height + 28), cap, fill=(160, 160, 170), font=f_small)
    return sheet


def main(args) -> int:
    scenes = read_json(args.szenen) if args.szenen else None
    if args.video:
        if not scenes:
            raise ToolError("--video braucht --szenen (scenes.json aus 'mgt timetable').")
        images = extract_frames(Path(args.video), scenes, Path(args.frames_ordner), args.position)
    else:
        src = Path(args.ordner)
        if not src.is_dir():
            raise ToolError(f"Ordner nicht gefunden: {src}")
        images = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXT)
    captions = {s["id"]: s["text"] for s in scenes["szenen"]} if scenes else {}
    sheet = build_sheet(images, args.spalten, args.breite, captions, args.safe_area, args.titel)
    out = Path(args.aus)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"Storyboard mit {len(images)} Bildern: {out} ({sheet.width}x{sheet.height})")
    if args.safe_area:
        print("Rote Flächen = Bereiche, in denen kein wichtiger Text/Inhalt stehen darf.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("storyboard", help="Tool 7: Screenshots oder Video-Frames zu einem Storyboard-Sheet")
    p.add_argument("ordner", nargs="?", default="05_Code/storyboard", help="Ordner mit Screenshots (Standard: 05_Code/storyboard)")
    p.add_argument("--video", help="statt Screenshots: Frames aus diesem Video holen (braucht --szenen)")
    p.add_argument("--szenen", help="scenes.json (für Bildunterschriften bzw. Frame-Zeitpunkte)")
    p.add_argument("--position", type=float, default=0.5, help="Zeitpunkt innerhalb der Szene 0–1 (Standard 0.5)")
    p.add_argument("--frames-ordner", default="05_Code/storyboard/frames", help="Ablage der Video-Frames")
    p.add_argument("--spalten", type=int, default=3, help="Spalten (Standard 3)")
    p.add_argument("--breite", type=int, default=480, help="Breite eines Vorschaubildes in px")
    p.add_argument("--safe-area", choices=list(SAFE_AREAS), help="Safe-Area-Overlay einblenden (shorts oder 16:9)")
    p.add_argument("--titel", help="Überschrift des Sheets")
    p.add_argument("--aus", default="05_Code/storyboard/storyboard.png", help="Ausgabedatei")
    p.set_defaults(func=main)
