"""Tool 8 – Export-Finisher: Format/FPS/Codec prüfen, Musik mischen, auf -14 LUFS / -1 dBTP normalisieren (Phase 6.3/6.4)."""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from .common import ToolError, ffprobe, require_binary, run

FORMATS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}


def video_info(path: str | Path) -> dict:
    data = ffprobe(path)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {"dauer": float(data["format"].get("duration", 0) or 0), "video": None, "audio": None}
    if v:
        rate = v.get("avg_frame_rate") or "0/0"
        if rate == "0/0":
            rate = v.get("r_frame_rate") or "0/1"
        fps = float(Fraction(rate)) if rate != "0/0" else 0.0
        info["video"] = {"codec": v.get("codec_name"), "breite": int(v["width"]), "hoehe": int(v["height"]),
                         "fps": round(fps, 3), "pix_fmt": v.get("pix_fmt")}
    if a:
        info["audio"] = {"codec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate", 0)),
                         "kanaele": int(a.get("channels", 0))}
    return info


def check_spec(info: dict, fmt: str, fps: float) -> list[str]:
    problems = []
    v = info["video"]
    if v is None:
        return ["Keine Videospur gefunden."]
    w, h = FORMATS[fmt]
    if (v["breite"], v["hoehe"]) != (w, h):
        problems.append(f"Auflösung {v['breite']}x{v['hoehe']} statt {w}x{h} ({fmt}).")
    if abs(v["fps"] - fps) > 0.01:
        problems.append(f"Bildrate {v['fps']} statt {fps} FPS.")
    if v["codec"] != "h264":
        problems.append(f"Video-Codec {v['codec']} statt h264.")
    if v["pix_fmt"] not in ("yuv420p", "yuvj420p"):
        problems.append(f"Pixelformat {v['pix_fmt']} statt yuv420p (manche Player zeigen sonst nichts).")
    if info["audio"] is None:
        problems.append("Keine Tonspur gefunden.")
    return problems


_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def parse_loudnorm(stderr: str) -> dict:
    m = _JSON_RE.search(stderr)
    if not m:
        raise ToolError("Lautheitsmessung lieferte kein Ergebnis (hat die Datei eine Tonspur?).")
    return json.loads(m.group(0))


def measure_loudness(path: str | Path, target: float = -14, tp: float = -1, lra: float = 11) -> dict:
    ffmpeg = require_binary("ffmpeg")
    proc = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn",
                "-af", f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"])
    m = parse_loudnorm(proc.stderr.decode("utf-8", "replace"))
    return {"lufs": float(m["input_i"]), "true_peak": float(m["input_tp"]), "lra": float(m["input_lra"]),
            "thresh": float(m["input_thresh"]), "offset": float(m["target_offset"])}


def build_command(src: Path, dst: Path, measured: dict, target: float, tp: float, lra: float,
                  music: Path | None = None, music_db: float = -18.0, reencode: bool = False) -> list[str]:
    ffmpeg = require_binary("ffmpeg")
    norm = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={measured['lufs']}:"
            f"measured_TP={measured['true_peak']}:measured_LRA={measured['lra']}:"
            f"measured_thresh={measured['thresh']}:offset={measured['offset']}:linear=true")
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(src)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        fc = (f"[1:a]volume={music_db}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[mix];"
              f"[mix]{norm}[a]")
        cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v:0?", "-map", "0:a:0", "-af", norm]
    if reencode:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(dst)]
    return cmd


def premix_measure(src: Path, music: Path, music_db: float, target, tp, lra) -> dict:
    """Bei Musik: zuerst die Mischung messen (in temporäre WAV), damit Pass 2 stimmt."""
    import tempfile

    ffmpeg = require_binary("ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        mix = Path(tmp) / "mix.wav"
        run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(music),
             "-filter_complex", f"[1:a]volume={music_db}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "[a]", str(mix)])
        return measure_loudness(mix, target, tp, lra)


def main(args) -> int:
    src = Path(args.eingang)
    info = video_info(src)
    v = info["video"]
    print(f"Eingang: {src}  ({info['dauer']:.2f} s)")
    if v:
        print(f"  Video: {v['breite']}x{v['hoehe']}, {v['fps']} FPS, {v['codec']}, {v['pix_fmt']}")
    if info["audio"]:
        a = info["audio"]
        print(f"  Audio: {a['codec']}, {a['sample_rate']} Hz, {a['kanaele']} Kanäle")
    problems = check_spec(info, args.format, args.fps)
    for p in problems:
        print("  WARNUNG: " + p)
    if info["audio"] is None:
        return 1
    before = measure_loudness(src, args.lufs, args.true_peak, args.lra)
    print(f"  Lautheit: {before['lufs']:.1f} LUFS, True Peak {before['true_peak']:.1f} dBTP")
    if args.nur_pruefen:
        ok = not problems and abs(before["lufs"] - args.lufs) <= 1 and before["true_peak"] <= args.true_peak + 0.2
        print("Ergebnis: " + ("passt" if ok else "Nacharbeit nötig"))
        return 0 if ok else 1

    music = Path(args.musik) if args.musik else None
    measured = premix_measure(src, music, args.musik_pegel, args.lufs, args.true_peak, args.lra) if music else before
    dst = Path(args.aus)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.resolve() == src.resolve():
        raise ToolError("Ausgabe darf nicht die Eingabedatei sein.")
    reencode = args.neu_kodieren or any("Codec" in p or "Pixelformat" in p for p in problems)
    run(build_command(src, dst, measured, args.lufs, args.true_peak, args.lra, music, args.musik_pegel, reencode))
    after = measure_loudness(dst, args.lufs, args.true_peak, args.lra)
    print(f"Ausgabe: {dst}")
    print(f"  Lautheit: {after['lufs']:.1f} LUFS, True Peak {after['true_peak']:.1f} dBTP "
          f"(Ziel {args.lufs} LUFS / {args.true_peak} dBTP)")
    ok = abs(after["lufs"] - args.lufs) <= 1.0 and after["true_peak"] <= args.true_peak + 0.5
    remaining = [p for p in check_spec(video_info(dst), args.format, args.fps)]
    for p in remaining:
        print("  WARNUNG: " + p)
    print("Ergebnis: " + ("fertig für den Upload" if ok and not remaining else "bitte prüfen"))
    return 0 if ok else 1


def register(sub) -> None:
    p = sub.add_parser("finish", help="Tool 8: Format prüfen und Ton auf -14 LUFS normalisieren")
    p.add_argument("eingang", help="gerendertes Video, z. B. 05_Code/out/render.mp4")
    p.add_argument("--aus", default="06_Export/final.mp4", help="Ziel (Standard: 06_Export/final.mp4)")
    p.add_argument("--format", choices=list(FORMATS), default="16:9", help="erwartetes Format (Standard 16:9)")
    p.add_argument("--fps", type=float, default=30, help="erwartete Bildrate (Standard 30)")
    p.add_argument("--lufs", type=float, default=-14, help="Ziel-Lautheit (Standard -14)")
    p.add_argument("--true-peak", type=float, default=-1, help="max. True Peak (Standard -1)")
    p.add_argument("--lra", type=float, default=11, help="Loudness Range (Standard 11)")
    p.add_argument("--musik", help="optionale Musikdatei, wird unter das Video gemischt (wird geloopt)")
    p.add_argument("--musik-pegel", type=float, default=-18, help="Musik-Lautstärke in dB (Standard -18)")
    p.add_argument("--neu-kodieren", action="store_true", help="Video zu H.264/yuv420p neu kodieren")
    p.add_argument("--nur-pruefen", action="store_true", help="nur messen und prüfen, nichts schreiben")
    p.set_defaults(func=main)
