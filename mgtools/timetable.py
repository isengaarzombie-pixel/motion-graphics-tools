"""Tool 3 – Timetable-Generator: Wort-Timestamps -> Szenen-JSON mit Frame-Nummern + timetable.md (Phase 3.5)."""
from __future__ import annotations

import math
import re
from pathlib import Path

from .common import ToolError, ffprobe, load_words, read_json, write_json

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


def _norm(token: str) -> str:
    return _PUNCT.sub("", token.lower())


def to_frame(t: float, fps: float) -> int:
    return int(math.floor(t * fps + 1e-6))


def split_sentences(words: list[dict], min_words: int = 1) -> list[int]:
    """Start-Indizes der Szenen: jeder Satz (endet auf . ! ? …) wird eine Szene."""
    starts = [0] if words else []
    for i, w in enumerate(words[:-1]):
        if re.search(r"[.!?…]['\"»“”)]*$", w["word"]):
            if i + 1 - starts[-1] >= min_words:
                starts.append(i + 1)
    return starts


def find_phrase(words: list[dict], phrase: str, start_at: int) -> int:
    tokens = [_norm(t) for t in phrase.split() if _norm(t)]
    if not tokens:
        raise ToolError(f"Leere Startphrase: '{phrase}'")
    normed = [_norm(w["word"]) for w in words]
    for i in range(start_at, len(words) - len(tokens) + 1):
        if normed[i:i + len(tokens)] == tokens:
            return i
    raise ToolError(f"Startphrase nicht im Timing gefunden (ab Wort {start_at}): '{phrase}'")


def build_scenes(words: list[dict], fps: float, defs: list[dict] | None = None,
                 total: float | None = None, tail: float = 0.5) -> dict:
    if not words:
        raise ToolError("Timing enthält keine Wörter.")
    ids: list[str] = []
    extra: list[dict] = []
    if defs:
        starts, pos = [], 0
        for k, d in enumerate(defs):
            if "start_wort" in d:
                idx = int(d["start_wort"])
            elif "start" in d and isinstance(d["start"], str):
                idx = find_phrase(words, d["start"], pos)
            elif k == 0:
                idx = 0
            else:
                raise ToolError(f"Szene {k + 1}: 'start' (Phrase) oder 'start_wort' (Index) fehlt.")
            if starts and idx <= starts[-1]:
                raise ToolError(f"Szene '{d.get('id', k + 1)}' beginnt nicht nach der vorherigen.")
            starts.append(idx)
            pos = idx + 1
            ids.append(str(d.get("id", f"szene_{k + 1:02d}")))
            extra.append({k2: v for k2, v in d.items() if k2 not in ("id", "start", "start_wort")})
        if starts[0] != 0:
            starts.insert(0, 0)
            ids.insert(0, "vorlauf")
            extra.insert(0, {})
    else:
        starts = split_sentences(words)
        ids = [f"szene_{k + 1:02d}" for k in range(len(starts))]
        extra = [{} for _ in starts]

    # mit bekannter Audiodauer exakt diese übernehmen, sonst letztes Wort + Nachlauf
    end_time = max(total, words[-1]["end"]) if total else words[-1]["end"] + tail
    total_frames = math.ceil(end_time * fps - 1e-6)
    scenes = []
    for k, s_idx in enumerate(starts):
        e_idx = starts[k + 1] if k + 1 < len(starts) else len(words)
        chunk = words[s_idx:e_idx]
        start_t = 0.0 if k == 0 else chunk[0]["start"]
        end_t = words[e_idx]["start"] if e_idx < len(words) else end_time
        sf, ef = to_frame(start_t, fps), (to_frame(end_t, fps) if e_idx < len(words) else total_frames)
        scenes.append({
            "id": ids[k],
            "text": " ".join(w["word"] for w in chunk),
            "start": round(start_t, 3), "end": round(end_t, 3),
            "startFrame": sf, "endFrame": ef, "durationInFrames": ef - sf,
            **extra[k],
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"],
                       "frame": to_frame(w["start"], fps), "endFrame": to_frame(w["end"], fps),
                       "relFrame": to_frame(w["start"], fps) - sf} for w in chunk],
        })
    return {"fps": fps, "dauer_sekunden": round(end_time, 3), "dauer_frames": total_frames,
            "szenen": scenes}


def timetable_markdown(data: dict) -> str:
    lines = [
        "# Timetable",
        "",
        f"FPS: {data['fps']} · Gesamtdauer: {data['dauer_sekunden']} s ({data['dauer_frames']} Frames)",
        "",
        "Spalten *Visuelle Aktion*, *Kamera* und *SFX* bitte pro Szene ausfüllen.",
        "",
        "| Szene | Zeit (s) | Frames | Sprechertext | Visuelle Aktion | Kamera | SFX |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in data["szenen"]:
        text = s["text"].replace("|", "\\|")
        lines.append(f"| {s['id']} | {s['start']:.2f}–{s['end']:.2f} | {s['startFrame']}–{s['endFrame']} "
                     f"| {text} | {s.get('aktion', '')} | {s.get('kamera', '')} | {s.get('sfx', '')} |")
    lines.append("")
    return "\n".join(lines)


def main(args) -> int:
    words = load_words(args.timing)
    defs = None
    if args.szenen:
        raw = read_json(args.szenen)
        defs = raw["szenen"] if isinstance(raw, dict) else raw
    total = None
    if args.audio:
        total = float(ffprobe(args.audio)["format"]["duration"])
    data = build_scenes(words, args.fps, defs, total=total, tail=args.nachlauf)
    write_json(args.aus, data)
    Path(args.md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.md).write_text(timetable_markdown(data), encoding="utf-8")
    print(f"{len(data['szenen'])} Szenen, {data['dauer_frames']} Frames @ {args.fps} fps")
    for s in data["szenen"]:
        print(f"  {s['id']:<14} Frame {s['startFrame']:>5}–{s['endFrame']:<5} {s['text'][:60]}")
    print(f"JSON: {args.aus}\nMarkdown: {args.md}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("timetable", help="Tool 3: timing.json -> scenes.json (Frames) + timetable.md")
    p.add_argument("timing", nargs="?", default="03_Audio/timing.json", help="Wort-Timing (Standard: 03_Audio/timing.json)")
    p.add_argument("--fps", type=float, default=30, help="Bildrate (Standard 30)")
    p.add_argument("--szenen", help="optionale Szenendefinition (JSON, s. README); ohne: ein Satz = eine Szene")
    p.add_argument("--audio", help="Audio, um die Gesamtdauer exakt zu übernehmen (z. B. 03_Audio/voice.mp3)")
    p.add_argument("--nachlauf", type=float, default=0.5, help="Sekunden nach dem letzten Wort (Standard 0.5)")
    p.add_argument("--aus", default="05_Code/scenes.json", help="Ausgabe-JSON (Standard: 05_Code/scenes.json)")
    p.add_argument("--md", default="03_Audio/timetable.md", help="Ausgabe-Markdown (Standard: 03_Audio/timetable.md)")
    p.set_defaults(func=main)
