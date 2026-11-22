"""Tool 1 – Projekt-Setup: Ordnerstruktur, Startdateien und Basis-Check (Phase 0)."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

FOLDERS = ["01_Referenzen", "02_Brand", "03_Audio", "04_Assets", "05_Code", "06_Export"]

GITIGNORE = """# Motion-Graphics-Projekt
.venv/
node_modules/
06_Export/
.env
__pycache__/
.DS_Store
"""

ENV_EXAMPLE = """# Kopiere diese Datei nach .env und trage deine Schlüssel ein. .env wird NIE committet.
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
"""

STATUS_TEMPLATE = """# STATUS

Stand: {today}

## Aktuelle Phase
Phase 0: System-Hygiene & Basis-Fundament

## Erledigt
- Ordnerstruktur angelegt

## Nächster Schritt
- Projektidee und Referenzen abfragen (Phase 1)

## Offene Fragen
-

## Tool-Versionen
{versions}
"""

LIZENZEN_TEMPLATE = """# Lizenzen externer Assets

| Datei | Quelle (Link) | Urheber | Lizenz | Abrufdatum | Notiz |
|---|---|---|---|---|---|
"""

# Name -> (Befehl, Mindest-Hauptversion oder None)
CHECKS = {
    "git": (["git", "--version"], None),
    "node": (["node", "--version"], 18),
    "npm": (["npm", "--version"], None),
    "python": (["python3", "--version"], 3),
    "ffmpeg": (["ffmpeg", "-version"], None),
    "ffprobe": (["ffprobe", "-version"], None),
}

INSTALL_HINTS = {
    "Windows": "winget install {pkg}",
    "Darwin": "brew install {pkg}",
    "Linux": "sudo apt install {pkg}",
}
PKG_NAMES = {
    "Windows": {"git": "Git.Git", "node": "OpenJS.NodeJS.LTS", "npm": "OpenJS.NodeJS.LTS",
                "python": "Python.Python.3.12", "ffmpeg": "Gyan.FFmpeg", "ffprobe": "Gyan.FFmpeg"},
    "Darwin": {"git": "git", "node": "node", "npm": "node", "python": "python",
               "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg"},
    "Linux": {"git": "git", "node": "nodejs", "npm": "npm", "python": "python3",
              "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg"},
}


def _version_of(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe and cmd[0] == "python3":
        exe = shutil.which("python") or shutil.which("py")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    if not text:
        return None
    m = re.search(r"v?(\d+(?:\.\d+)+)", text[0])
    return m.group(1) if m else text[0]


def check_tools() -> list[dict]:
    system = platform.system()
    results = []
    for name, (cmd, min_major) in CHECKS.items():
        version = _version_of(cmd)
        ok = version is not None
        note = ""
        if ok and min_major is not None:
            try:
                major = int(version.split(".")[0])
                if major < min_major:
                    ok = False
                    note = f"zu alt (mind. {min_major})"
            except ValueError:
                pass
        if version is None:
            pkg = PKG_NAMES.get(system, PKG_NAMES["Linux"]).get(name, name)
            note = "fehlt – installieren mit: " + INSTALL_HINTS.get(system, "{pkg}").format(pkg=pkg)
        results.append({"tool": name, "version": version, "ok": ok, "note": note})
    return results


def create_project(root: Path, git_init: bool = False, versions: list[dict] | None = None) -> list[str]:
    """Legt Ordner und Startdateien an. Bestehende Dateien werden nie überschrieben."""
    root.mkdir(parents=True, exist_ok=True)
    created = []
    for folder in FOLDERS:
        p = root / folder
        if not p.exists():
            p.mkdir()
            (p / ".gitkeep").touch()
            created.append(folder + "/")
    (root / "05_Code" / "tools").mkdir(parents=True, exist_ok=True)
    (root / "05_Code" / "i18n").mkdir(parents=True, exist_ok=True)

    vers = "\n".join(f"- {v['tool']}: {v['version'] or 'nicht installiert'}" for v in (versions or []))
    files = {
        ".gitignore": GITIGNORE,
        ".env.example": ENV_EXAMPLE,
        "STATUS.md": STATUS_TEMPLATE.format(today=date.today().isoformat(), versions=vers or "- "),
        "lizenzen.md": LIZENZEN_TEMPLATE,
        "05_Code/i18n/de.json": "{}\n",
    }
    for rel, content in files.items():
        p = root / rel
        if not p.exists():
            p.write_text(content, encoding="utf-8")
            created.append(rel)

    if git_init and not (root / ".git").exists():
        if shutil.which("git"):
            subprocess.run(["git", "init", "-q"], cwd=root, check=False)
            created.append(".git/")
    return created


def main(args) -> int:
    root = Path(args.ordner).resolve()
    versions = [] if args.ohne_check else check_tools()
    created = create_project(root, git_init=args.git, versions=versions)
    print(f"Projektordner: {root}")
    print("Neu angelegt: " + (", ".join(created) if created else "nichts (alles vorhanden)"))
    if versions:
        print("\nBasis-Check:")
        for v in versions:
            mark = "OK " if v["ok"] else "FEHLT"
            print(f"  [{mark}] {v['tool']:<8} {v['version'] or '-':<12} {v['note']}")
    missing = [v for v in versions if not v["ok"]]
    return 1 if missing and args.streng else 0


def register(sub) -> None:
    p = sub.add_parser("setup", help="Tool 1: Projektordner 01–06 anlegen und Git/Node/Python/FFmpeg prüfen")
    p.add_argument("ordner", nargs="?", default=".", help="Projektordner (Standard: aktueller Ordner)")
    p.add_argument("--git", action="store_true", help="zusätzlich 'git init' ausführen")
    p.add_argument("--ohne-check", action="store_true", help="Basis-Check überspringen")
    p.add_argument("--streng", action="store_true", help="Exit-Code 1, wenn ein Tool fehlt")
    p.set_defaults(func=main)
