"""Tool 9 – Checkpoint & Report: STATUS.md pflegen + Git-Commit, REPORT.md erzeugen (Globale Regeln, Phase 9)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from .common import ToolError, read_json

SECTIONS = ["Aktuelle Phase", "Erledigt", "Nächster Schritt", "Offene Fragen", "Tool-Versionen"]


# ---------------------------------------------------------------- STATUS.md

def parse_status(text: str) -> "OrderedDict[str, list[str]]":
    sections: "OrderedDict[str, list[str]]" = OrderedDict()
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    for k in sections:
        while sections[k] and not sections[k][-1].strip():
            sections[k].pop()
        while sections[k] and not sections[k][0].strip():
            sections[k].pop(0)
    return sections


def render_status(sections: "OrderedDict[str, list[str]]", stamp: str) -> str:
    out = ["# STATUS", "", f"Stand: {stamp}", ""]
    for name, lines in sections.items():
        out.append(f"## {name}")
        out.extend(lines if lines else ["- "])
        out.append("")
    return "\n".join(out)


def _items(lines: list[str]) -> list[str]:
    return [l for l in lines if l.strip() and l.strip() != "-"]


def update_status(path: Path, phase: str | None = None, done: list[str] | None = None,
                  next_step: str | None = None, questions: list[str] | None = None,
                  resolved: list[str] | None = None, versions: list[str] | None = None) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    sec = parse_status(text)
    for name in SECTIONS:
        sec.setdefault(name, [])
    if phase:
        sec["Aktuelle Phase"] = [phase]
    if done:
        sec["Erledigt"] = _items(sec["Erledigt"]) + [f"- {d}" for d in done]
    if next_step:
        sec["Nächster Schritt"] = [f"- {next_step}"]
    if questions:
        sec["Offene Fragen"] = _items(sec["Offene Fragen"]) + [f"- {q}" for q in questions]
    if resolved:
        keep = []
        for line in _items(sec["Offene Fragen"]):
            if any(r.lower() in line.lower() for r in resolved):
                continue
            keep.append(line)
        sec["Offene Fragen"] = keep
    if versions:
        existing = {re.sub(r"^-\s*", "", l).split(":")[0].strip(): l for l in _items(sec["Tool-Versionen"])}
        for v in versions:
            name = v.split(":")[0].strip()
            existing[name] = f"- {v}"
        sec["Tool-Versionen"] = list(existing.values())
    new = render_status(sec, datetime.now().strftime("%Y-%m-%d %H:%M"))
    path.write_text(new, encoding="utf-8")
    return new


def git_commit(root: Path, message: str) -> str:
    if not shutil.which("git"):
        raise ToolError("git ist nicht installiert.")
    if not (root / ".git").exists():
        raise ToolError("Kein Git-Repo im Projektordner. Zuerst: mgt setup --git")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    proc = subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        msg = (proc.stdout + proc.stderr).strip()
        if "nothing to commit" in msg or "nichts zu committen" in msg:
            return "nichts zu committen"
        raise ToolError("git commit fehlgeschlagen: " + msg)
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                          text=True).stdout.strip()


def status_main(args) -> int:
    root = Path(args.projekt)
    path = root / "STATUS.md"
    if args.zeigen:
        print(path.read_text(encoding="utf-8") if path.exists() else "Keine STATUS.md vorhanden.")
        return 0
    update_status(path, args.phase, args.erledigt, args.naechster, args.frage, args.frage_erledigt, args.version)
    print(f"STATUS.md aktualisiert: {path}")
    if args.commit:
        print(f"Commit: {git_commit(root, args.commit)}")
    return 0


# ---------------------------------------------------------------- REPORT.md

def git_log(root: Path) -> list[dict]:
    if not shutil.which("git") or not (root / ".git").exists():
        return []
    proc = subprocess.run(["git", "log", "--reverse", "--format=%H%x09%aI%x09%s"], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            out.append({"hash": parts[0][:7], "zeit": datetime.fromisoformat(parts[1]), "nachricht": parts[2]})
    return out


def phase_times(commits: list[dict]) -> "OrderedDict[str, float]":
    """Zeit pro Phase grob aus Commits schätzen: Abstand zum vorherigen Commit wird der Phase des
    aktuellen Commits zugeschlagen (Pausen > 2 h werden ignoriert)."""
    result: "OrderedDict[str, float]" = OrderedDict()
    prev = None
    for c in commits:
        m = re.match(r"\s*(Phase\s*\d+|[^:]+):", c["nachricht"], re.I)
        key = m.group(1).strip() if m else "ohne Phase"
        delta = 0.0 if prev is None else (c["zeit"] - prev).total_seconds() / 60
        if delta > 120:
            delta = 0.0
        result[key] = result.get(key, 0.0) + delta
        prev = c["zeit"]
    return result


def node_versions(root: Path) -> list[str]:
    out = []
    for pkg in sorted(root.glob("05_Code/**/package.json")):
        if "node_modules" in pkg.parts:
            continue
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sect in ("dependencies", "devDependencies"):
            for name, ver in data.get(sect, {}).items():
                installed = root / pkg.parent.relative_to(root) / "node_modules" / name / "package.json"
                if installed.exists():
                    try:
                        ver = json.loads(installed.read_text(encoding="utf-8")).get("version", ver)
                    except (OSError, json.JSONDecodeError):
                        pass
                out.append(f"{name}: {ver}")
    return out


def credits(root: Path) -> list[str]:
    log = root / "03_Audio" / "credits_log.json"
    if not log.exists():
        return []
    entries = read_json(log)
    total: dict[str, int] = {}
    for e in entries:
        key = f"{e.get('dienst', '?')} ({e.get('einheit', 'Zeichen')})"
        total[key] = total.get(key, 0) + int(e.get("menge", 0))
    return [f"{k}: {v}" for k, v in total.items()]


def build_report(root: Path, tokens: str | None = None, costs: str | None = None,
                 extra_credits: list[str] | None = None) -> str:
    from .licenses import read_entries
    from .setup_project import check_tools

    old_learnings = ""
    rp = root / "REPORT.md"
    if rp.exists():
        m = re.search(r"## Learnings.*", rp.read_text(encoding="utf-8", errors="replace"), re.S)
        old_learnings = m.group(0).strip() if m else ""

    commits = git_log(root)
    times = phase_times(commits)
    tools = check_tools()
    lines = ["# Produktionsbericht", "", f"Erstellt: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    lines += ["## Kosten & Verbrauch", "",
              f"- Geschätzter Tokenverbrauch: {tokens or '(bitte eintragen)'}",
              f"- API-Kosten: {costs or '(bitte eintragen)'}"]
    for c in credits(root) + (extra_credits or []):
        lines.append(f"- Credits: {c}")
    lines += ["", "## Zeitaufwand pro Phase (aus Git-Commits geschätzt)", ""]
    if times:
        for k, v in times.items():
            lines.append(f"- {k}: {v:.0f} min")
        if commits:
            span = commits[-1]["zeit"] - commits[0]["zeit"]
            lines.append(f"- Gesamt zwischen erstem und letztem Commit: {span}")
    else:
        lines.append("- keine Git-Historie gefunden")
    lines += ["", "## Tool-Versionen", ""]
    lines += [f"- {t['tool']}: {t['version'] or 'nicht installiert'}" for t in tools]
    lines += [f"- {v}" for v in node_versions(root)]
    lines += ["", "## Projekt-Kennzahlen", ""]
    exports = sorted((root / "06_Export").glob("*.mp4")) if (root / "06_Export").exists() else []
    for e in exports:
        try:
            from .finish import video_info
            info = video_info(e)
            v = info["video"] or {}
            lines.append(f"- {e.name}: {info['dauer']:.1f} s, {v.get('breite')}x{v.get('hoehe')}, {v.get('fps')} FPS")
        except Exception:
            lines.append(f"- {e.name}")
    assets = [p for p in (root / "04_Assets").rglob("*") if p.is_file() and p.name != ".gitkeep"] \
        if (root / "04_Assets").exists() else []
    lines.append(f"- Assets: {len(assets)} Dateien, Lizenz-Einträge: {len(read_entries(root / 'lizenzen.md'))}")
    lines.append(f"- Commits: {len(commits)}")
    lines += [""]
    lines += [old_learnings or "## Learnings & Snippets fürs Master-Template\n\n- (bitte eintragen)"]
    lines.append("")
    return "\n".join(lines)


def report_main(args) -> int:
    root = Path(args.projekt)
    text = build_report(root, args.tokens, args.kosten, args.credits)
    (root / "REPORT.md").write_text(text, encoding="utf-8")
    print(f"REPORT.md geschrieben: {root / 'REPORT.md'}")
    print("Offene Platzhalter '(bitte eintragen)' bitte ergänzen." if "(bitte eintragen)" in text else "")
    return 0


def register(sub) -> None:
    p = sub.add_parser("status", help="Tool 9a: STATUS.md aktualisieren und optional committen (Checkpoint)")
    p.add_argument("--phase", help="aktuelle Phase, z. B. 'Phase 3: Skript & Audio'")
    p.add_argument("--erledigt", nargs="*", help="erledigte Schritte anhängen")
    p.add_argument("--naechster", help="nächster konkreter Schritt (ersetzt den alten)")
    p.add_argument("--frage", nargs="*", help="offene Fragen anhängen")
    p.add_argument("--frage-erledigt", nargs="*", help="offene Fragen entfernen (Textteil genügt)")
    p.add_argument("--version", nargs="*", help="Tool-Versionen eintragen, z. B. 'remotion: 4.0.300'")
    p.add_argument("--commit", help="danach 'git add -A && git commit -m <Text>'")
    p.add_argument("--zeigen", action="store_true", help="STATUS.md nur anzeigen")
    p.add_argument("--projekt", default=".", help="Projektordner")
    p.set_defaults(func=status_main)

    r = sub.add_parser("report", help="Tool 9b: REPORT.md (Kosten, Zeit pro Phase, Versionen) erzeugen")
    r.add_argument("--tokens", help="geschätzter Tokenverbrauch, z. B. '1,2 Mio.'")
    r.add_argument("--kosten", help="API-Kosten, z. B. '4,80 €'")
    r.add_argument("--credits", nargs="*", help="weitere Credits, z. B. 'Higgsfield: 40'")
    r.add_argument("--projekt", default=".", help="Projektordner")
    r.set_defaults(func=report_main)
