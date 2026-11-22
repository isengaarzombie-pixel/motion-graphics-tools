"""Tool 11 – Brand-Checker: Farben und Schriften im Code gegen 02_Brand/brand.md prüfen (Phase 1.2/7.1)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import ToolError

HEX_RE = re.compile(r"(?<![\w&])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])")
RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})", re.I)
HSL_RE = re.compile(r"hsla?\(\s*(\d+(?:\.\d+)?)(?:deg)?\s*[, ]\s*(\d+(?:\.\d+)?)%\s*[, ]\s*(\d+(?:\.\d+)?)%", re.I)
FONT_RE = re.compile(r"""font-?family\s*[:=]\s*[{(]?\s*([`'"]?)([^;}\n]+?)\1\s*[,;})\n]""", re.I)
FONT_IMPORT_RE = re.compile(r"""@remotion/google-fonts/([A-Za-z0-9]+)""")
GFONTS_RE = re.compile(r"""fonts\.googleapis\.com/css2?\?family=([A-Za-z0-9+]+)""")
NAMED_RE = re.compile(r"""(?:color|fill|stroke|background(?:-color)?|backgroundColor|borderColor)\s*[:=]\s*['"]?(orange|red|blue|green|yellow|purple|pink|cyan|magenta|teal|navy|gold|lime)\b""", re.I)

WEIGHT_RE = re.compile(r"\d{3}|\d+\s*(px|pt|rem|em)?|(?:extra|semi)?\s*(bold|regular|medium|light|thin|black|italic)", re.I)
GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "cursive", "fantasy", "inherit",
                 "initial", "unset", "ui-sans-serif", "ui-serif", "ui-monospace", "-apple-system",
                 "blinkmacsystemfont", "emoji", "math", "var"}
NEUTRAL = {"#000000", "#ffffff"}
CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".scss", ".html", ".svg", ".json",
            ".py", ".vue", ".svelte"}
SKIP_DIRS = {"node_modules", "dist", "build", "out", ".remotion", ".next", ".git", ".venv", "public/fonts"}
FORBID_WORDS = re.compile(r"verbot|verboten|nicht verwenden|nie |niemals|kein[e]? |never|don't|❌|🚫", re.I)
FONT_KEYS = re.compile(r"^\s*[-*]?\s*(?:\*\*)?(fonts?|schrift(?:art)?(?:en)?|headline|headlines|überschrift(?:en)?|"
                       r"body|fließtext|fliesstext|text|display|akzent)(?:\*\*)?\s*:\s*(.+)$", re.I)


def norm_hex(h: str) -> str:
    h = h.lstrip("#").lower()
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    return "#" + h[:6]


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = norm_hex(h)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hsl_to_hex(h: float, s: float, l: float) -> str:
    import colorsys

    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def distance(a: str, b: str) -> float:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def _clean_font(name: str) -> str:
    name = name.strip().strip("`'\"*_ ").strip()
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    name = re.split(r"\s+[–—-]\s+|\s+\d{3}\b|,\s*(?:bold|regular|medium|light)", name)[0].strip()
    return name


def parse_brand(path: Path) -> dict:
    if not path.exists():
        raise ToolError(f"Brand File nicht gefunden: {path}")
    allowed, forbidden, fonts = set(), set(), set()
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^#{1,6}\s+(.*)", line)
        if h:
            section = h.group(1).lower()
            continue
        colors = {norm_hex(m.group(0)) for m in HEX_RE.finditer(line)}
        if colors:
            if "verbot" in section or FORBID_WORDS.search(line):
                forbidden |= colors
            else:
                allowed |= colors
        if "verbot" in section:
            continue
        m = FONT_KEYS.match(line)
        in_typo = any(k in section for k in ("typo", "schrift", "font"))
        if m:
            for part in re.split(r",|/|\bund\b|;", m.group(2)):
                n = _clean_font(part)
                if n and not HEX_RE.search(n) and len(n) < 40 and not WEIGHT_RE.fullmatch(n):
                    fonts.add(n)
        elif in_typo:
            for n in re.findall(r"`([^`]+)`|\*\*([^*]+)\*\*", line):
                name = _clean_font(n[0] or n[1])
                if name and len(name) < 40 and not FONT_KEYS.match(name + ":"):
                    fonts.add(name)
    allowed -= forbidden
    return {"farben": sorted(allowed), "verboten": sorted(forbidden), "fonts": sorted(fonts)}


def iter_code_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in CODE_EXT:
            continue
        rel = p.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts) or \
                any(rel.startswith(s + "/") for s in SKIP_DIRS):
            continue
        if p.name in ("package.json", "package-lock.json", "tsconfig.json", "scenes.json") or p.name.endswith(".min.js"):
            continue
        yield p


def check_code(root: Path, brand: dict, tolerance: float = 0, allow_neutral: bool = True) -> list[dict]:
    allowed = set(brand["farben"]) | (NEUTRAL if allow_neutral else set())
    forbidden = set(brand["verboten"])
    fonts = {f.lower() for f in brand["fonts"]}
    findings = []

    def color_ok(hx: str) -> tuple[bool, str]:
        if hx in forbidden:
            return False, "verbotene Farbe"
        if hx in allowed:
            return True, ""
        if tolerance and any(distance(hx, a) <= tolerance for a in allowed):
            return True, ""
        nearest = min(allowed, key=lambda a: distance(hx, a)) if allowed else None
        return False, f"nicht im Brand File (nächste: {nearest})" if nearest else "nicht im Brand File"

    for f in iter_code_files(root):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        rel = f.relative_to(root).as_posix()
        for no, line in enumerate(lines, 1):
            found = [(m.group(0), norm_hex(m.group(0))) for m in HEX_RE.finditer(line)]
            found += [(m.group(0) + ")", "#{:02x}{:02x}{:02x}".format(*(min(255, int(x)) for x in m.groups())))
                      for m in RGB_RE.finditer(line)]
            found += [(m.group(0) + ")", hsl_to_hex(*(float(x) for x in m.groups()))) for m in HSL_RE.finditer(line)]
            for raw, hx in found:
                ok, why = color_ok(hx)
                if not ok:
                    findings.append({"datei": rel, "zeile": no, "art": "farbe", "wert": raw, "hex": hx, "grund": why})
            for m in NAMED_RE.finditer(line):
                findings.append({"datei": rel, "zeile": no, "art": "farbe", "wert": m.group(1),
                                 "grund": "benannte CSS-Farbe statt Brand-Farbe"})
            if fonts:
                names = []
                for m in FONT_RE.finditer(line):
                    names += [n.strip().strip("'\"` ") for n in m.group(2).split(",")]
                names += FONT_IMPORT_RE.findall(line)
                names += [n.replace("+", " ") for n in GFONTS_RE.findall(line)]
                for n in names:
                    low = n.lower()
                    if not n or low in GENERIC_FONTS or low.startswith(("var(", "$", "{", "theme")) or \
                            re.fullmatch(r"[a-z_][\w.]*", n):  # Variable statt Literal
                        continue
                    if not any(low == f or low.replace(" ", "") == f.replace(" ", "") for f in fonts):
                        findings.append({"datei": rel, "zeile": no, "art": "schrift", "wert": n,
                                         "grund": f"nicht im Brand File ({', '.join(brand['fonts'])})"})
    return findings


def main(args) -> int:
    brand = parse_brand(Path(args.brand))
    if args.farben:
        brand["farben"] = sorted({norm_hex(c) for c in args.farben})
    if args.fonts:
        brand["fonts"] = args.fonts
    if not brand["farben"]:
        raise ToolError("Keine Farben (#hex) im Brand File gefunden.")
    findings = check_code(Path(args.code), brand, args.toleranz, not args.streng)
    if args.json:
        print(json.dumps({"brand": brand, "verstoesse": findings}, ensure_ascii=False, indent=2))
        return 1 if findings else 0
    print(f"Brand-Farben: {', '.join(brand['farben'])}")
    if brand["verboten"]:
        print(f"Verbotene Farben: {', '.join(brand['verboten'])}")
    print(f"Schriften: {', '.join(brand['fonts']) or '(keine erkannt – Prüfung übersprungen)'}")
    if not findings:
        print("Keine Verstöße gefunden.")
        return 0
    print(f"\n{len(findings)} Verstöße:")
    for f in findings:
        print(f"  {f['datei']}:{f['zeile']}  {f['art']} {f['wert']}  – {f['grund']}")
    return 1


def register(sub) -> None:
    p = sub.add_parser("brand", help="Tool 11: Farben und Schriften im Code gegen brand.md prüfen")
    p.add_argument("--brand", default="02_Brand/brand.md", help="Brand File (Standard: 02_Brand/brand.md)")
    p.add_argument("--code", default="05_Code", help="Code-Ordner (Standard: 05_Code)")
    p.add_argument("--toleranz", type=float, default=0, help="erlaubte RGB-Abweichung (0 = exakt, z. B. 6)")
    p.add_argument("--streng", action="store_true", help="auch reines Weiß/Schwarz nur erlauben, wenn im Brand File")
    p.add_argument("--farben", nargs="*", help="Farbliste statt Brand File")
    p.add_argument("--fonts", nargs="*", help="Schriftliste statt Brand File")
    p.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    p.set_defaults(func=main)
