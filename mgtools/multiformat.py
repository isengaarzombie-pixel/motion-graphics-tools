"""Tool 12 – Multi-Format-Export: 16:9 <-> 9:16 (und 1:1, 4:5) per Neu-Render-Schleife oder FFmpeg-Reframing (Phase 6.3)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .common import ToolError, require_binary, run
from .finish import FORMATS


def reframe_filter(mode: str, w: int, h: int, focus_x: float = 0.5, focus_y: float = 0.5,
                   color: str = "black", blur: int = 40, fps: float | None = None) -> str:
    fx, fy = min(max(focus_x, 0), 1), min(max(focus_y, 0), 1)
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-{w})*{fx}:(ih-{h})*{fy}"
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    tail = f",setsar=1" + (f",fps={fps}" if fps else "") + ",format=yuv420p"
    if mode == "crop":
        return f"[0:v]{cover}{tail}[v]"
    if mode == "pad":
        return f"[0:v]{fit},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}{tail}[v]"
    if mode == "blur":
        return (f"[0:v]split=2[bg][fg];[bg]{cover},gblur=sigma={blur},eq=brightness=-0.08[bgb];"
                f"[fg]{fit}[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2{tail}[v]")
    raise ToolError(f"Unbekannter Modus '{mode}' (crop, pad, blur).")


def reframe(src: Path, dst: Path, fmt: str, mode: str = "blur", focus_x: float = 0.5, focus_y: float = 0.5,
            color: str = "black", fps: float | None = None, crf: int = 18) -> Path:
    if fmt not in FORMATS:
        raise ToolError(f"Unbekanntes Format '{fmt}'. Möglich: {', '.join(FORMATS)}")
    if not src.exists():
        raise ToolError(f"Video nicht gefunden: {src}")
    ffmpeg = require_binary("ffmpeg")
    w, h = FORMATS[fmt]
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-filter_complex",
         reframe_filter(mode, w, h, focus_x, focus_y, color, fps=fps),
         "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
         "-c:a", "copy", "-movflags", "+faststart", str(dst)])
    return dst


def fill_template(template: str, **values) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def render_loop(template: str, items: list[dict], dry_run: bool = False, cwd: str | None = None) -> list[str]:
    """Führt einen Render-Befehl pro Eintrag aus; Platzhalter {format}, {breite}, {hoehe}, {name}, {lang}."""
    cmds = []
    for it in items:
        cmd = fill_template(template, **it)
        cmds.append(cmd)
        print(("[Probe] " if dry_run else "[Render] ") + cmd, flush=True)
        if not dry_run:
            proc = subprocess.run(cmd, shell=True, cwd=cwd)
            if proc.returncode != 0:
                raise ToolError(f"Render fehlgeschlagen (Exit {proc.returncode}): {cmd}")
    return cmds


def format_items(formats: list[str]) -> list[dict]:
    items = []
    for f in formats:
        if f not in FORMATS:
            raise ToolError(f"Unbekanntes Format '{f}'. Möglich: {', '.join(FORMATS)}")
        w, h = FORMATS[f]
        items.append({"format": f, "breite": w, "hoehe": h, "name": f.replace(":", "x")})
    return items


def main(args) -> int:
    if args.aktion == "render":
        if not args.befehl:
            raise ToolError("render braucht --befehl, z. B. \"npx remotion render Main out/{name}.mp4 "
                            "--width={breite} --height={hoehe}\"")
        render_loop(args.befehl, format_items(args.formate), args.probe, args.arbeitsordner)
        return 0
    if not args.eingang:
        raise ToolError("umwandeln braucht ein Eingangsvideo.")
    src = Path(args.eingang)
    for f in args.formate:
        dst = Path(args.ordner) / f"{src.stem}_{f.replace(':', 'x')}.mp4"
        reframe(src, dst, f, args.modus, args.fokus_x, args.fokus_y, args.farbe, args.fps)
        print(f"{f} ({args.modus}): {dst}")
    print("Hinweis: Reframing ist die schnelle Lösung. Für Text-lastige Szenen besser pro Format neu "
          "rendern (mgt formate render …) und Safe Areas mit 'mgt storyboard --safe-area shorts' prüfen.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("formate", help="Tool 12: 16:9/9:16 erzeugen (FFmpeg-Reframing oder Render-Schleife)")
    p.add_argument("aktion", choices=["umwandeln", "render"], help="umwandeln = vorhandenes Video reframen; render = Befehl pro Format")
    p.add_argument("eingang", nargs="?", help="Eingangsvideo (bei umwandeln)")
    p.add_argument("--formate", nargs="+", default=["9:16"], help=f"Zielformate ({', '.join(FORMATS)}), Standard 9:16")
    p.add_argument("--modus", choices=["blur", "crop", "pad"], default="blur",
                   help="blur = unscharfer Hintergrund (Standard), crop = Ausschnitt, pad = Balken")
    p.add_argument("--fokus-x", type=float, default=0.5, help="Bildausschnitt horizontal 0 (links) – 1 (rechts) bei crop")
    p.add_argument("--fokus-y", type=float, default=0.5, help="Bildausschnitt vertikal 0 (oben) – 1 (unten) bei crop")
    p.add_argument("--farbe", default="black", help="Balkenfarbe bei pad (z. B. black oder 0x101418)")
    p.add_argument("--fps", type=float, help="Bildrate erzwingen (z. B. 30)")
    p.add_argument("--ordner", default="06_Export", help="Zielordner (Standard: 06_Export)")
    p.add_argument("--befehl", help="Render-Befehl mit Platzhaltern {format} {breite} {hoehe} {name}")
    p.add_argument("--arbeitsordner", help="Ordner, in dem der Render-Befehl läuft (z. B. 05_Code)")
    p.add_argument("--probe", action="store_true", help="Befehle nur anzeigen, nicht ausführen")
    p.set_defaults(func=main)
