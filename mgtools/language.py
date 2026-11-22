"""Tool 13 – Sprach-Pipeline DE -> EN: i18n-Dateien vorbereiten/prüfen, Voiceover mit Timestamps über
ElevenLabs erzeugen, Timing pro Sprache aufbereiten und pro Sprache rendern (Phase 7.4).

Die Übersetzung selbst macht das LLM: ``mgt sprache vorlage`` legt die Zieldatei mit TODO-Markern an,
das LLM ersetzt die TODOs, ``mgt sprache pruefen`` kontrolliert das Ergebnis.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .common import (ToolError, ffprobe, load_dotenv, read_json, require_binary, run, words_from_alignment,
                     write_json)

API_BASE = "https://api.elevenlabs.io/v1"
TODO = "TODO: "
# Nur diese Modelle akzeptieren laut API-Doku das Feld language_code
LANGUAGE_ENFORCING_MODELS = ("turbo_v2_5", "flash_v2_5")
PLACEHOLDER_RE = re.compile(r"\{\{?[^{}]+\}?\}|<[^<>]+>|%\w|\$\{[^}]+\}")


# ---------------------------------------------------------------- i18n

def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def make_template(src: dict, existing: dict | None = None) -> tuple[dict, int]:
    """Zielstruktur wie src; vorhandene Übersetzungen bleiben, neue Texte bekommen 'TODO: <Quelltext>'."""
    existing = existing or {}
    count = 0

    def walk(s, e):
        nonlocal count
        if isinstance(s, dict):
            e = e if isinstance(e, dict) else {}
            return {k: walk(v, e.get(k)) for k, v in s.items()}
        if isinstance(s, list):
            e = e if isinstance(e, list) else []
            return [walk(v, e[i] if i < len(e) else None) for i, v in enumerate(s)]
        if isinstance(s, str):
            if isinstance(e, str) and e.strip():
                return e
            count += 1
            return TODO + s
        return s if e is None else e

    return walk(src, existing), count


def check_translation(src: dict, dst: dict) -> dict:
    s, d = dict(_flatten(src)), dict(_flatten(dst))
    res = {"fehlend": [], "ueberzaehlig": [], "todo": [], "leer": [], "unveraendert": [], "platzhalter": [],
           "laenge": []}
    for k, v in s.items():
        if k not in d:
            res["fehlend"].append(k)
            continue
        t = d[k]
        if not isinstance(v, str):
            continue
        if not isinstance(t, str) or not t.strip():
            res["leer"].append(k)
            continue
        if t.startswith(TODO):
            res["todo"].append(k)
            continue
        if t == v and len(v) > 3 and re.search(r"[a-zA-ZäöüÄÖÜß]{4,}", v):
            res["unveraendert"].append(k)
        if sorted(PLACEHOLDER_RE.findall(v)) != sorted(PLACEHOLDER_RE.findall(t)):
            res["platzhalter"].append(k)
        if len(v) >= 12 and len(t) > len(v) * 1.4:
            res["laenge"].append(k)
    res["ueberzaehlig"] = [k for k in d if k not in s]
    return res


# ---------------------------------------------------------------- ElevenLabs TTS

def split_text(text: str, max_chars: int = 4500) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[.!?…])\s+|\n{2,}", text)
    chunks, cur = [], ""
    for p in parts:
        if not p:
            continue
        while len(p) > max_chars:  # extrem langer Satz: an Wortgrenze teilen
            cut = p.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            if cur.strip():
                chunks.append(cur.strip())
                cur = ""
            chunks.append(p[:cut].strip())
            p = p[cut:].strip()
        if len(cur) + len(p) + 1 > max_chars and cur:
            chunks.append(cur.strip())
            cur = ""
        cur += p + " "
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def tts_request(text: str, voice_id: str, api_key: str, model: str, language: str | None = None,
                output_format: str = "mp3_44100_128", previous_text: str | None = None,
                next_text: str | None = None, voice_settings: dict | None = None,
                retries: int = 4, session=None) -> dict:
    import requests

    http = session or requests
    url = f"{API_BASE}/text-to-speech/{voice_id}/with-timestamps"
    body: dict = {"text": text, "model_id": model}
    if language and any(m in model for m in LANGUAGE_ENFORCING_MODELS):
        body["language_code"] = language  # andere Modelle lehnen language_code ab
    if previous_text:
        body["previous_text"] = previous_text
    if next_text:
        body["next_text"] = next_text
    if voice_settings:
        body["voice_settings"] = voice_settings
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    delay = 2.0
    for attempt in range(retries + 1):
        resp = http.post(url, json=body, headers=headers, params={"output_format": output_format}, timeout=300)
        if resp.status_code == 200:
            data = resp.json()
            if "audio_base64" not in data:
                raise ToolError("Antwort von ElevenLabs enthält kein Audio.")
            return data
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        detail = resp.text[:500]
        if "api_key_id_used_as_api_key" in detail:
            raise ToolError("In ELEVENLABS_API_KEY steht die Key-ID, nicht der API-Key. Den eigentlichen Key "
                            "(beginnt mit 'sk_', wird nur beim Erstellen angezeigt) in .env eintragen.")
        if resp.status_code == 401 or "invalid_api_key" in detail:
            raise ToolError(f"ElevenLabs lehnt den API-Key ab ({resp.status_code}). "
                            "ELEVENLABS_API_KEY in .env prüfen.")
        raise ToolError(f"ElevenLabs-Fehler {resp.status_code}: {detail}")
    raise ToolError("ElevenLabs nicht erreichbar.")


def merge_alignments(parts: list[tuple[dict, float]]) -> dict:
    """[(alignment, offset_sekunden)] zu einem Alignment zusammenführen (Leerzeichen dazwischen)."""
    chars, starts, ends = [], [], []
    for i, (al, off) in enumerate(parts):
        if i > 0:
            last = ends[-1] if ends else off
            chars.append(" ")
            starts.append(last)
            ends.append(off)
        chars += list(al["characters"])
        starts += [round(t + off, 4) for t in al["character_start_times_seconds"]]
        ends += [round(t + off, 4) for t in al["character_end_times_seconds"]]
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


def log_credits(project: Path, service: str, amount: int, unit: str = "Zeichen", note: str = "") -> None:
    path = project / "03_Audio" / "credits_log.json"
    entries = read_json(path) if path.exists() else []
    entries.append({"zeit": datetime.now().isoformat(timespec="seconds"), "dienst": service,
                    "menge": amount, "einheit": unit, "notiz": note})
    write_json(path, entries)


def synthesize(text: str, out_audio: Path, out_timing: Path, voice_id: str, api_key: str, model: str,
               language: str | None = None, max_chars: int = 4500, project: Path = Path("."),
               session=None) -> dict:
    chunks = split_text(text, max_chars)
    results = []
    for i, chunk in enumerate(chunks):
        prev = chunks[i - 1][-300:] if i > 0 else None
        nxt = chunks[i + 1][:300] if i + 1 < len(chunks) else None
        results.append(tts_request(chunk, voice_id, api_key, model, language, previous_text=prev,
                                   next_text=nxt, session=session))
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    if len(results) == 1:
        out_audio.write_bytes(base64.b64decode(results[0]["audio_base64"]))
        alignment = results[0].get("alignment") or results[0].get("normalized_alignment")
    else:
        ffmpeg = require_binary("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            files, offsets, off = [], [], 0.0
            for i, r in enumerate(results):
                f = Path(tmp) / f"teil_{i:03d}.mp3"
                f.write_bytes(base64.b64decode(r["audio_base64"]))
                files.append(f)
                offsets.append(off)
                off += float(ffprobe(f)["format"]["duration"])
            lst = Path(tmp) / "liste.txt"
            lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
            run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                 str(out_audio)])
        alignment = merge_alignments([(r.get("alignment") or r.get("normalized_alignment"), o)
                                      for r, o in zip(results, offsets)])
    timing = {"quelle": "elevenlabs/with-timestamps", "modell": model, "stimme": voice_id,
              "sprache": language, "alignment": alignment, "words": words_from_alignment(alignment)}
    write_json(out_timing, timing)
    log_credits(project, "ElevenLabs TTS", len(text), "Zeichen", f"{model}, {language or 'auto'}")
    return timing


def _key_and_voice(args) -> tuple[str, str]:
    load_dotenv(Path(args.projekt) / ".env")
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice = (args.stimme or os.environ.get(f"ELEVENLABS_VOICE_ID_{(args.sprache or '').upper()}")
             or os.environ.get("ELEVENLABS_VOICE_ID", "")).strip()
    if not key:
        raise ToolError("ELEVENLABS_API_KEY fehlt. In .env eintragen (nie committen): ELEVENLABS_API_KEY=...")
    if not voice:
        raise ToolError("Keine Stimme: --stimme VOICE_ID angeben oder ELEVENLABS_VOICE_ID in .env setzen.")
    return key, voice


# ---------------------------------------------------------------- CLI

def main(args) -> int:
    project = Path(args.projekt)
    i18n = project / "05_Code" / "i18n"
    if args.aktion == "vorlage":
        src = read_json(i18n / f"{args.von}.json")
        dst_path = i18n / f"{args.nach}.json"
        existing = read_json(dst_path) if dst_path.exists() else None
        data, todo = make_template(src, existing)
        write_json(dst_path, data)
        print(f"{dst_path}: {todo} Texte zum Übersetzen (markiert mit '{TODO}').")
        print("Nächster Schritt: LLM ersetzt jedes 'TODO: <deutscher Text>' durch die Übersetzung, "
              f"danach: mgt sprache pruefen --nach {args.nach}")
        return 0
    if args.aktion == "pruefen":
        res = check_translation(read_json(i18n / f"{args.von}.json"), read_json(i18n / f"{args.nach}.json"))
        labels = {"fehlend": "Schlüssel fehlen", "ueberzaehlig": "überzählige Schlüssel", "todo": "noch TODO",
                  "leer": "leer", "unveraendert": "identisch mit Quelltext (übersetzt?)",
                  "platzhalter": "Platzhalter/Tags stimmen nicht überein",
                  "laenge": "deutlich länger als das Original (Layout prüfen)"}
        hard = ("fehlend", "todo", "leer", "platzhalter")
        bad = False
        for k, label in labels.items():
            if res[k]:
                bad = bad or k in hard
                print(f"{'FEHLER' if k in hard else 'Hinweis'} – {label}: {', '.join(res[k])}")
        print("Übersetzung vollständig." if not bad else "Bitte korrigieren.")
        return 1 if bad else 0
    if args.aktion == "tts":
        if not args.text:
            raise ToolError("tts braucht --text (Datei mit dem Sprechertext dieser Sprache).")
        key, voice = _key_and_voice(args)
        text = Path(args.text).read_text(encoding="utf-8")
        audio_dir = project / "03_Audio" / args.sprache
        timing = synthesize(text, audio_dir / "voice_raw.mp3", audio_dir / "timing_raw.json", voice, key,
                            args.modell, args.sprache, args.max_zeichen, project)
        print(f"Voiceover: {audio_dir / 'voice_raw.mp3'}")
        print(f"Timing: {audio_dir / 'timing_raw.json'} ({len(timing['words'])} Wörter, {len(text)} Zeichen)")
        print(f"Weiter: mgt pausen {audio_dir / 'voice_raw.mp3'} --timing {audio_dir / 'timing_raw.json'} "
              f"--aus {audio_dir / 'voice.mp3'} --timing-aus {audio_dir / 'timing.json'} "
              f"--schnittliste {audio_dir / 'schnittliste.json'}")
        return 0
    if args.aktion == "pipeline":
        # tts -> pausen -> timetable für eine Sprache
        from types import SimpleNamespace

        from . import pauses, timetable

        if not args.text:
            raise ToolError("pipeline braucht --text.")
        key, voice = _key_and_voice(args)
        d = project / "03_Audio" / args.sprache
        synthesize(Path(args.text).read_text(encoding="utf-8"), d / "voice_raw.mp3", d / "timing_raw.json",
                   voice, key, args.modell, args.sprache, args.max_zeichen, project)
        pauses.main(SimpleNamespace(audio=str(d / "voice_raw.mp3"), timing=str(d / "timing_raw.json"),
                                    aus=str(d / "voice.mp3"), timing_aus=str(d / "timing.json"),
                                    schnittliste=str(d / "schnittliste.json"), max_pause=args.max_pause,
                                    ziel=args.ziel, aus_audio=False, schwelle_db=-40.0, raender_behalten=False,
                                    nur_timing=False, schnittliste_ein=None))
        timetable.main(SimpleNamespace(timing=str(d / "timing.json"), fps=args.fps, szenen=args.szenen,
                                       audio=str(d / "voice.mp3"), nachlauf=0.5,
                                       aus=str(project / "05_Code" / f"scenes_{args.sprache}.json"),
                                       md=str(d / "timetable.md")))
        return 0
    if args.aktion == "render":
        from .multiformat import render_loop

        if not args.befehl:
            raise ToolError("render braucht --befehl mit {lang}, z. B. \"npx remotion render Main "
                            "out/video_{lang}.mp4 --props=./scenes_{lang}.json\"")
        items = [{"lang": l, "timing": f"03_Audio/{l}/timing.json", "szenen": f"05_Code/scenes_{l}.json",
                  "audio": f"03_Audio/{l}/voice.mp3"} for l in args.sprachen]
        render_loop(args.befehl, items, args.probe, args.arbeitsordner)
        return 0
    raise ToolError(f"Unbekannte Aktion {args.aktion}")


def register(sub) -> None:
    p = sub.add_parser("sprache", help="Tool 13: i18n-Vorlage/Prüfung, ElevenLabs-TTS mit Timestamps, Render pro Sprache")
    p.add_argument("aktion", choices=["vorlage", "pruefen", "tts", "pipeline", "render"])
    p.add_argument("--von", default="de", help="Quellsprache (Standard de)")
    p.add_argument("--nach", default="en", help="Zielsprache (Standard en)")
    p.add_argument("--sprache", default="en", help="Sprache für tts/pipeline (Standard en)")
    p.add_argument("--sprachen", nargs="+", default=["de", "en"], help="Sprachen für render")
    p.add_argument("--text", help="Sprechertext-Datei für tts/pipeline")
    p.add_argument("--stimme", help="ElevenLabs Voice-ID (sonst ELEVENLABS_VOICE_ID[_EN] aus .env)")
    p.add_argument("--modell", default="eleven_multilingual_v2", help="ElevenLabs-Modell (Standard eleven_multilingual_v2)")
    p.add_argument("--max-zeichen", type=int, default=4500, help="Text wird in Stücke dieser Länge geteilt")
    p.add_argument("--max-pause", type=float, default=0.4, help="pipeline: Pausen-Grenze")
    p.add_argument("--ziel", type=float, default=0.25, help="pipeline: Restpause")
    p.add_argument("--fps", type=float, default=30, help="pipeline: FPS für scenes_<lang>.json")
    p.add_argument("--szenen", help="pipeline: Szenendefinition (wie bei timetable)")
    p.add_argument("--befehl", help="render: Befehl mit {lang} {timing} {szenen} {audio}")
    p.add_argument("--arbeitsordner", help="render: Ordner, in dem der Befehl läuft")
    p.add_argument("--probe", action="store_true", help="render: Befehle nur anzeigen")
    p.add_argument("--projekt", default=".", help="Projektordner")
    p.set_defaults(func=main)
