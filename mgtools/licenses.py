"""Tool 6 – Lizenz-Logger: Einträge in lizenzen.md pflegen und Assets ohne Nachweis finden (Phase 4.4/8.3)."""
from __future__ import annotations

import fnmatch
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .common import ToolError
from .setup_project import LIZENZEN_TEMPLATE

COLUMNS = ["Datei", "Quelle (Link)", "Urheber", "Lizenz", "Abrufdatum", "Notiz"]

# Quellen, die laut Workflow NIE ins Video dürfen (nur Referenz)
FORBIDDEN_HOSTS = ["pinterest.", "pin.it", "images.google.", "google.com/imgres", "savee.",
                   "fiverr.", "upwork."]
CHECK_HOSTS = {"archive.org": "Archive.org ist nicht automatisch gemeinfrei – Lizenz pro Objekt prüfen.",
               "pixabay.com": "Pixabay-Lizenz prüfen (z. B. keine Nutzung erkennbarer Personen/Marken ohne Freigabe).",
               "pexels.com": "Pexels-Lizenz prüfen.", "unsplash.com": "Unsplash-Lizenz prüfen."}
OWN_LICENSES = {"eigen", "selbst erstellt", "eigenproduktion", "ki-generiert (eigen)", "own"}
DEFAULT_SCAN = ["04_Assets", "03_Audio/musik"]
DEFAULT_IGNORE = [".gitkeep", "*.md", ".DS_Store", "Thumbs.db"]


def _split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _split_row(line)
        if not cells or cells[0] in ("Datei", "") or set(cells[0]) <= set("-: "):
            continue
        cells += [""] * (len(COLUMNS) - len(cells))
        entries.append(dict(zip(COLUMNS, cells[: len(COLUMNS)])))
    return entries


def source_warnings(url: str) -> tuple[bool, list[str]]:
    """(verboten, hinweise) für eine Quell-URL."""
    low = url.lower()
    forbidden = any(h in low for h in FORBIDDEN_HOSTS)
    hints = [msg for host, msg in CHECK_HOSTS.items() if host in low]
    if forbidden:
        hints.insert(0, "Diese Quelle ist laut Workflow nur Referenz (01_Referenzen) und darf nicht ins Video.")
    return forbidden, hints


def add_entry(path: Path, datei: str, quelle: str, urheber: str, lizenz: str, datum: str | None = None,
              notiz: str = "", force: bool = False) -> list[str]:
    if not lizenz.strip():
        raise ToolError("Ohne Lizenzangabe wird kein Eintrag angelegt (Asset nicht verwenden).")
    forbidden, hints = source_warnings(quelle)
    if forbidden and not force:
        raise ToolError(hints[0] + " (Mit --trotzdem nur eintragen, wenn eine echte Lizenz vorliegt.)")
    if quelle and lizenz.lower() not in OWN_LICENSES and not urlparse(quelle).scheme:
        hints.append("Quelle ist kein Link – bitte möglichst die genaue URL angeben.")
    if not path.exists():
        path.write_text(LIZENZEN_TEMPLATE, encoding="utf-8")
    existing = {e["Datei"] for e in read_entries(path)}
    if datei in existing and not force:
        raise ToolError(f"'{datei}' steht schon in {path}. Mit --trotzdem trotzdem hinzufügen.")
    values = [datei, quelle, urheber, lizenz, datum or date.today().isoformat(), notiz]
    row = "| " + " | ".join(v.replace("|", "\\|") for v in values) + " |\n"
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + row, encoding="utf-8")
    return hints


def check(root: Path, lic_path: Path, scan: list[str], ignore: list[str]) -> dict:
    entries = read_entries(lic_path)
    listed = {e["Datei"].replace("\\", "/") for e in entries}
    listed_names = {Path(n).name for n in listed}
    missing = []
    for d in scan:
        base = root / d
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(f.name, pat) or fnmatch.fnmatch(rel, pat) for pat in ignore):
                continue
            if rel in listed or f.name in listed_names:
                continue
            missing.append(rel)
    incomplete = [e["Datei"] for e in entries if not e["Lizenz"] or
                  (e["Lizenz"].lower() not in OWN_LICENSES and not e["Quelle (Link)"])]
    forbidden = [e["Datei"] for e in entries if source_warnings(e["Quelle (Link)"])[0]]
    return {"eintraege": len(entries), "ohne_nachweis": missing, "unvollstaendig": incomplete,
            "verbotene_quelle": forbidden}


def main(args) -> int:
    root = Path(args.projekt)
    lic = root / "lizenzen.md"
    if args.aktion == "add":
        if not args.datei or args.lizenz is None:
            raise ToolError("add braucht DATEI und --lizenz (sowie --quelle und --urheber).")
        hints = add_entry(lic, args.datei, args.quelle or "", args.urheber or "", args.lizenz,
                          args.datum, args.notiz or "", args.trotzdem)
        print(f"Eingetragen in {lic}: {args.datei}")
        for h in hints:
            print("Hinweis: " + h)
        return 0
    if args.aktion == "liste":
        entries = read_entries(lic)
        if not entries:
            print("Keine Einträge.")
        for e in entries:
            print(f"- {e['Datei']} · {e['Lizenz']} · {e['Urheber']} · {e['Quelle (Link)']} · {e['Abrufdatum']}")
        return 0
    # pruefen
    res = check(root, lic, args.ordner or DEFAULT_SCAN, DEFAULT_IGNORE + (args.ignorieren or []))
    print(f"{res['eintraege']} Einträge in {lic}")
    ok = True
    for key, label in [("ohne_nachweis", "Dateien ohne Lizenz-Eintrag"),
                       ("unvollstaendig", "Einträge ohne Lizenz oder Quelle"),
                       ("verbotene_quelle", "Einträge mit unzulässiger Quelle (Pinterest, Google-Bilder …)")]:
        if res[key]:
            ok = False
            print(f"\n{label}:")
            for item in res[key]:
                print(f"  - {item}")
    if ok:
        print("Alles belegt.")
    else:
        print("\nTipp: Selbst erstellte Dateien mit  mgt lizenz add <datei> --lizenz eigen  eintragen.")
    return 0 if ok else 1


def register(sub) -> None:
    p = sub.add_parser("lizenz", help="Tool 6: lizenzen.md pflegen (add / liste / pruefen)")
    p.add_argument("aktion", choices=["add", "liste", "pruefen"])
    p.add_argument("datei", nargs="?", help="Dateipfad relativ zum Projekt (bei add)")
    p.add_argument("--quelle", help="Link zur Quelle")
    p.add_argument("--urheber", help="Urheber/Autor")
    p.add_argument("--lizenz", help="z. B. CC0, CC BY 4.0, Pixabay License, eigen")
    p.add_argument("--datum", help="Abrufdatum (Standard: heute)")
    p.add_argument("--notiz", help="z. B. Namensnennung im Abspann nötig")
    p.add_argument("--trotzdem", action="store_true", help="Warnungen übergehen (nur mit echtem Nachweis)")
    p.add_argument("--projekt", default=".", help="Projektordner (Standard: aktueller Ordner)")
    p.add_argument("--ordner", nargs="*", help=f"zu prüfende Ordner (Standard: {' '.join(DEFAULT_SCAN)})")
    p.add_argument("--ignorieren", nargs="*", help="zusätzliche Muster, z. B. 'sfx_*' '*.svg'")
    p.set_defaults(func=main)
