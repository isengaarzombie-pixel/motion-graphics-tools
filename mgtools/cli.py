"""Gemeinsame Kommandozeile: ``mgt <befehl> …`` bzw. ``python -m mgtools <befehl> …``."""
from __future__ import annotations

import argparse
import sys

from . import (__version__, brand, checkpoint, cutout, finish, language, licenses, multiformat, pauses,
               pronounce, setup_project, sfx, storyboard, timetable)
from .common import ToolError

MODULES = [setup_project, pauses, timetable, sfx, cutout, licenses, storyboard, finish, checkpoint,
           pronounce, brand, multiformat, language]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mgt",
        description="Motion Graphics Tools – Hilfstools für den Audio-First-Workflow. "
                    "Alle Befehle laufen im Projektordner (01_Referenzen … 06_Export). "
                    "Hilfe zu einem Befehl: mgt <befehl> -h",
    )
    parser.add_argument("--version", action="version", version=f"mgt {__version__}")
    sub = parser.add_subparsers(dest="befehl", metavar="<befehl>")
    for m in MODULES:
        m.register(sub)
    return parser


def _safe_console() -> None:
    """Windows-Konsolen (cp1252) sollen bei Sonderzeichen nicht abstürzen."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _safe_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except ToolError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
