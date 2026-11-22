"""Tool 10 – Aussprache-Wandler: englische Begriffe/Abkürzungen im deutschen Sprechertext phonetisch schreiben (Phase 3.1)."""
from __future__ import annotations

import json
import re
from collections import Counter
from importlib import resources
from pathlib import Path

from .common import ToolError, read_json, write_json

EN_LETTERS = {"A": "Äi", "B": "Bie", "C": "Sie", "D": "Die", "E": "Ie", "F": "Eff", "G": "Dschie",
              "H": "Äitsch", "I": "Ai", "J": "Dschäi", "K": "Käi", "L": "Ell", "M": "Emm", "N": "Enn",
              "O": "Ou", "P": "Pie", "Q": "Kju", "R": "Ahr", "S": "Ess", "T": "Tie", "U": "Ju",
              "V": "Wie", "W": "Dabbelju", "X": "Ex", "Y": "Wai", "Z": "Sie"}
DE_LETTERS = {"A": "A", "B": "Be", "C": "Ze", "D": "De", "E": "E", "F": "Eff", "G": "Ge", "H": "Ha",
              "I": "I", "J": "Jott", "K": "Ka", "L": "Ell", "M": "Emm", "N": "Enn", "O": "O", "P": "Pe",
              "Q": "Ku", "R": "Err", "S": "Ess", "T": "Te", "U": "U", "V": "Fau", "W": "We", "X": "Ix",
              "Y": "Üpsilon", "Z": "Zett", "Ä": "Ä", "Ö": "Ö", "Ü": "Ü"}

# Großgeschriebene deutsche Wörter (Betonung), die NICHT buchstabiert werden
CAPS_WORDS = set("""ICH DU ER SIE ES WIR IHR DAS DER DIE DEN DEM DES UND ODER ABER KEIN KEINE KEINEN NICHT NIE
NIEMALS NUR JETZT HIER SEHR VIEL MEHR ALLE ALLES NEU WICHTIG ACHTUNG GRATIS SOFORT MUSS MUSST KANN WIRD IST
SIND WAR HAT HABEN BITTE DANKE JA NEIN GUT SCHLECHT FALSCH RICHTIG STOP STOPP TIPP NEUE GANZ WAS WIE WO WER
WARUM WANN DANN AUCH NOCH SCHON IMMER EIN EINE EINEN MIT OHNE FÜR VON ZU AUF AUS BEI NACH UM AM IM AN IN SO""".split())

ACRONYM_RE = re.compile(r"(?<![\w.])([A-ZÄÖÜ][A-ZÄÖÜa-z]{0,1}[A-ZÄÖÜ]{1,4})(s?)(?![\w])")


def load_dictionary(extra: list[str | Path] | None = None) -> dict:
    with resources.files("mgtools.data").joinpath("aussprache_de.json").open(encoding="utf-8") as f:
        base = json.load(f)
    terms = dict(base.get("begriffe", {}))
    abbr = dict(base.get("abkuerzungen", {}))
    german = set(base.get("deutsche_abkuerzungen", []))
    for path in extra or []:
        if not Path(path).exists():
            continue
        data = read_json(path)
        if "begriffe" in data or "abkuerzungen" in data:
            terms.update(data.get("begriffe", {}))
            abbr.update(data.get("abkuerzungen", {}))
            german.update(data.get("deutsche_abkuerzungen", []))
        else:  # einfaches {"Begriff": "Lautschrift"}
            terms.update({k: v for k, v in data.items() if not k.startswith("_")})
    return {"begriffe": terms, "abkuerzungen": abbr, "deutsche_abkuerzungen": german}


def spell(acronym: str, mode: str) -> str:
    letters = DE_LETTERS if mode == "de" else EN_LETTERS
    return " ".join(letters.get(ch.upper(), ch) for ch in acronym)


def convert(text: str, dictionary: dict, acronyms: str = "en") -> tuple[str, Counter]:
    """Gibt (Sprechertext, Zähler der Ersetzungen) zurück.

    acronyms: 'en' = unbekannte Abkürzungen englisch buchstabieren, 'de' = deutsch buchstabieren,
    'behalten' = unbekannte Abkürzungen unverändert lassen.
    """
    stats: Counter = Counter()
    terms = dictionary["begriffe"]
    abbr = dictionary["abkuerzungen"]
    german = dictionary["deutsche_abkuerzungen"]

    # 1) feste Einträge in einem Durchgang (längste zuerst), damit nichts doppelt ersetzt wird
    entries: dict[str, tuple[str, bool]] = {}
    for k, v in terms.items():
        entries[k] = (v, False)  # Groß/Klein egal
    for k, v in abbr.items():
        entries[k] = (v, True)  # exakte Schreibweise
    keys = sorted(entries, key=len, reverse=True)
    if keys:
        pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w])",
                             re.IGNORECASE)
        lower_map = {k.lower(): k for k in keys if not entries[k][1]}

        def _rep(m: re.Match) -> str:
            found = m.group(1)
            key = found if found in entries else lower_map.get(found.lower())
            if key is None or (entries[key][1] and found != key):
                return found
            stats[key] += 1
            return entries[key][0]

        text = pattern.sub(_rep, text)

    # 2) unbekannte Abkürzungen buchstabieren
    if acronyms != "behalten":
        def _acr(m: re.Match) -> str:
            core, plural = m.group(1), m.group(2)
            if core in CAPS_WORDS:
                return m.group(0)
            if core in german:
                mode = "de"
            else:
                mode = acronyms
            if not core.isupper() and core not in german:
                return m.group(0)
            stats[core + plural] += 1
            out = spell(core, mode)
            return out + ("s" if plural else "")

        text = ACRONYM_RE.sub(_acr, text)
    return text, stats


def _convert_json(obj, dictionary, acronyms, stats):
    if isinstance(obj, str):
        new, s = convert(obj, dictionary, acronyms)
        stats.update(s)
        return new
    if isinstance(obj, list):
        return [_convert_json(x, dictionary, acronyms, stats) for x in obj]
    if isinstance(obj, dict):
        return {k: _convert_json(v, dictionary, acronyms, stats) for k, v in obj.items()}
    return obj


def main(args) -> int:
    extra = [p for p in [args.woerterbuch, "02_Brand/aussprache.json"] if p]
    dictionary = load_dictionary(extra)
    if args.text is not None:
        out, stats = convert(args.text, dictionary, args.abkuerzungen)
        print(out)
    else:
        if not args.datei:
            raise ToolError("Bitte eine Datei oder --text angeben.")
        src = Path(args.datei)
        if not src.exists():
            raise ToolError(f"Datei nicht gefunden: {src}")
        dst = Path(args.aus) if args.aus else src.with_name(src.stem + "_sprecher" + src.suffix)
        if src.suffix.lower() == ".json":
            stats: Counter = Counter()
            write_json(dst, _convert_json(read_json(src), dictionary, args.abkuerzungen, stats))
        else:
            out, stats = convert(src.read_text(encoding="utf-8"), dictionary, args.abkuerzungen)
            dst.write_text(out, encoding="utf-8")
        print(f"Sprechertext: {dst}  (Original für Bild-Overlays bleibt unverändert: {src})")
    if stats:
        spelled = [k for k in stats if k not in dictionary["begriffe"] and k not in dictionary["abkuerzungen"]]
        if spelled:
            print("Automatisch buchstabiert (bitte prüfen, ggf. in 02_Brand/aussprache.json eintragen): "
                  + ", ".join(spelled))
        print("Ersetzt: " + ", ".join(f"{k} ×{v}" for k, v in stats.most_common()), flush=True)
    else:
        print("Keine Ersetzungen.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("aussprache", help="Tool 10: englische Begriffe im Sprechertext phonetisch schreiben")
    p.add_argument("datei", nargs="?", help="Sprechertext (.txt/.md/.json)")
    p.add_argument("--text", help="statt Datei: Text direkt umwandeln und ausgeben")
    p.add_argument("--aus", help="Ausgabedatei (Standard: <name>_sprecher.<endung>)")
    p.add_argument("--woerterbuch", help="eigenes Wörterbuch (JSON); 02_Brand/aussprache.json wird automatisch genutzt")
    p.add_argument("--abkuerzungen", choices=["en", "de", "behalten"], default="en",
                   help="unbekannte Abkürzungen englisch (Standard) oder deutsch buchstabieren oder behalten")
    p.set_defaults(func=main)
