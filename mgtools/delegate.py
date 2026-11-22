"""Tool 14 – Prüfen & Delegieren: Ergebnisse von Subagents oder günstigen Fremdmodellen automatisch prüfen,
Aufgaben an Modelle über eine OpenAI-kompatible API (Standard: OpenRouter) delegieren – mit Korrektur-Runden,
Eskalation zum nächsten Modell und einem Log, welches Modell welche Aufgabenart zuverlässig schafft.

Befehle:
  mgt pruefe <datei>        prüft eine Datei (SVG, JSON + Schema, Python, JS, HTML, Text, Testbefehl)
  mgt delegiere …           lässt ein Fremdmodell eine Aufgabe lösen und prüft das Ergebnis
  mgt modelle               Statistik und Empfehlung je Aufgabenart aus dem Log
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from .common import ToolError, load_dotenv, read_json

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
ARTEN = ["auto", "svg", "json", "python", "js", "html", "text"]
EXT_ART = {".svg": "svg", ".json": "json", ".py": "python", ".js": "js", ".mjs": "js", ".cjs": "js",
           ".jsx": "js", ".ts": "js", ".tsx": "js", ".html": "html", ".htm": "html", ".md": "text",
           ".txt": "text"}


def default_log_path() -> Path:
    env = os.environ.get("MGT_MODELL_LOG")
    return Path(env) if env else Path.home() / ".mgt" / "modell_log.jsonl"


# ================================================================ Prüfungen

def _svg_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def check_svg(text: str, brand: dict | None = None, max_kb: float | None = None) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return ["DOCTYPE/ENTITY ist nicht erlaubt (Sicherheitsrisiko)."], warnings
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        return [f"Kein gültiges XML: {exc}"], warnings
    if _svg_ns(root.tag) != "svg":
        errors.append(f"Wurzelelement ist <{_svg_ns(root.tag)}> statt <svg>.")
    if "viewBox" not in root.attrib:
        errors.append("viewBox fehlt (SVG skaliert sonst nicht sauber).")
    drawable = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "use", "image", "g"}
    tags = [_svg_ns(el.tag) for el in root.iter()]
    if not drawable & set(tags):
        errors.append("SVG enthält keine sichtbaren Elemente.")
    if "script" in tags or "foreignObject" in tags:
        errors.append("<script>/<foreignObject> sind nicht erlaubt.")
    for el in root.iter():
        for k, v in el.attrib.items():
            name = _svg_ns(k)
            if name.lower().startswith("on"):
                errors.append(f"Event-Attribut {name} ist nicht erlaubt.")
            if name == "href" and re.match(r"\s*(https?:|//|javascript:)", v, re.I):
                errors.append(f"Externer Verweis ist nicht erlaubt: {v[:60]}")
    if max_kb and len(text.encode("utf-8")) / 1024 > max_kb:
        errors.append(f"Datei größer als {max_kb} KB.")
    if brand:
        from .brand import HEX_RE, NEUTRAL, norm_hex

        allowed = set(brand.get("farben", [])) | NEUTRAL
        forbidden = set(brand.get("verboten", []))
        for m in HEX_RE.finditer(text):
            hx = norm_hex(m.group(0))
            if hx in forbidden:
                errors.append(f"Verbotene Farbe {m.group(0)}.")
            elif allowed and hx not in allowed:
                errors.append(f"Farbe {m.group(0)} steht nicht im Brand File.")
        if re.search(r"\b(orange|red|blue|green|yellow|purple|pink)\b", " ".join(
                v for el in root.iter() for k, v in el.attrib.items() if _svg_ns(k) in ("fill", "stroke"))):
            errors.append("Benannte CSS-Farbe statt Brand-Farbe in fill/stroke.")
    return sorted(set(errors), key=errors.index), warnings


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def validate_schema(data, schema: dict, path: str = "$") -> list[str]:
    """Kleiner JSON-Schema-Prüfer (type, required, properties, additionalProperties, items, enum, const,
    minimum, maximum, minLength, maxLength, minItems, maxItems, pattern)."""
    errs: list[str] = []
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for ty in types:
            if ty == "integer":
                ok = ok or (isinstance(data, int) and not isinstance(data, bool))
            elif ty == "number":
                ok = ok or (isinstance(data, (int, float)) and not isinstance(data, bool))
            elif ty in _TYPES:
                ok = ok or isinstance(data, _TYPES[ty])
        if not ok:
            return [f"{path}: Typ {type(data).__name__} statt {t}"]
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: Wert {data!r} nicht in {schema['enum']}")
    if "const" in schema and data != schema["const"]:
        errs.append(f"{path}: Wert muss {schema['const']!r} sein")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errs.append(f"{path}: {data} < Minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errs.append(f"{path}: {data} > Maximum {schema['maximum']}")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errs.append(f"{path}: Text kürzer als {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errs.append(f"{path}: Text länger als {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], data):
            errs.append(f"{path}: passt nicht zu Muster {schema['pattern']}")
    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                errs.append(f"{path}: Pflichtfeld '{req}' fehlt")
        props = schema.get("properties", {})
        for k, v in data.items():
            if k in props:
                errs += validate_schema(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unerwartetes Feld '{k}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errs += validate_schema(v, schema["additionalProperties"], f"{path}.{k}")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errs.append(f"{path}: weniger als {schema['minItems']} Einträge")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errs.append(f"{path}: mehr als {schema['maxItems']} Einträge")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(data):
                errs += validate_schema(item, schema["items"], f"{path}[{i}]")
    return errs


def check_json(text: str, schema: dict | None = None) -> tuple[list[str], list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"Kein gültiges JSON: {exc}"], []
    if schema:
        return validate_schema(data, schema), []
    return [], []


def check_python(text: str) -> tuple[list[str], list[str]]:
    try:
        compile(text, "<ergebnis>", "exec")
    except SyntaxError as exc:
        return [f"Python-Syntaxfehler Zeile {exc.lineno}: {exc.msg}"], []
    return [], []


def _balanced(text: str) -> str | None:
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    s = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    s = re.sub(r"`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "''", s)
    for i, ch in enumerate(s):
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return f"Klammer '{ch}' passt nicht (Zeichen {i})"
    return f"{len(stack)} Klammer(n) nicht geschlossen" if stack else None


def check_js(text: str, suffix: str = ".js") -> tuple[list[str], list[str]]:
    node = shutil.which("node")
    if node and suffix in (".js", ".mjs", ".cjs", ""):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=suffix or ".mjs", delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = f.name
        try:
            proc = subprocess.run([node, "--check", tmp], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
        finally:
            os.unlink(tmp)
        if proc.returncode != 0:
            msg = [l for l in proc.stderr.splitlines() if "Error" in l]
            return [f"JavaScript-Syntaxfehler: {msg[0] if msg else proc.stderr.strip()[:200]}"], []
        return [], []
    problem = _balanced(text)
    warn = [] if node else ["node nicht gefunden – nur Klammerprüfung."]
    if suffix in (".ts", ".tsx", ".jsx"):
        warn.append("TS/JSX nur grob geprüft (Klammern). Für volle Prüfung: --befehl \"npx tsc --noEmit\".")
    return ([problem] if problem else []), warn


IMPLICIT_CLOSE = {"p", "li", "td", "tr", "th", "html", "body", "head", "option", "dt", "dd", "thead", "tbody"}


class _HtmlCheck(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
            "path", "rect", "circle", "line", "polyline", "polygon", "ellipse", "stop", "use"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.count = [], [], 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.count += 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                t = self.stack.pop()
                if t not in IMPLICIT_CLOSE:
                    self.errors.append(f"<{t}> nicht geschlossen")
            self.stack.pop()
        else:
            self.errors.append(f"</{tag}> ohne öffnendes Tag")


def check_html(text: str) -> tuple[list[str], list[str]]:
    p = _HtmlCheck()
    p.feed(text)
    p.close()
    errors = list(p.errors)
    errors += [f"<{t}> nicht geschlossen" for t in p.stack if t not in IMPLICIT_CLOSE]
    if p.count == 0:
        errors.append("Keine HTML-Elemente gefunden.")
    return errors, []


def check_text(text: str) -> tuple[list[str], list[str]]:
    return ([] if text.strip() else ["Ergebnis ist leer."]), []


def run_command(cmd: str, cwd: str | None = None) -> list[str]:
    proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
        return [f"Befehl '{cmd}' fehlgeschlagen (Exit {proc.returncode}):\n" + "\n".join(tail)]
    return []


def detect_art(path: Path | None, text: str) -> str:
    if path is not None and path.suffix.lower() in EXT_ART:
        return EXT_ART[path.suffix.lower()]
    s = text.lstrip()
    if s.startswith("<svg") or (s.startswith("<?xml") and "<svg" in s[:500]):
        return "svg"
    if s[:1] in "{[":
        return "json"
    if s.lower().startswith(("<!doctype html", "<html")):
        return "html"
    return "text"


def check_content(text: str, art: str, path: Path | None = None, schema: dict | None = None,
                  brand: dict | None = None, max_kb: float | None = None, command: str | None = None,
                  cwd: str | None = None) -> dict:
    if art == "auto":
        art = detect_art(path, text)
    if art == "svg":
        errors, warnings = check_svg(text, brand, max_kb)
    elif art == "json":
        errors, warnings = check_json(text, schema)
    elif art == "python":
        errors, warnings = check_python(text)
    elif art == "js":
        errors, warnings = check_js(text, path.suffix.lower() if path else ".js")
    elif art == "html":
        errors, warnings = check_html(text)
    else:
        errors, warnings = check_text(text)
    if command and not errors:
        errors += run_command(command, cwd)
    return {"art": art, "ok": not errors, "fehler": errors, "hinweise": warnings}


# ================================================================ Log & Statistik

def log_result(entry: dict, path: Path | None = None) -> None:
    p = path or default_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"zeit": datetime.now().isoformat(timespec="seconds"), **entry}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(path: Path | None = None) -> list[dict]:
    p = path or default_log_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def statistics(entries: list[dict]) -> dict:
    """{aufgabenart: {modell: {aufgaben, erfolge, quote, versuche_avg, kosten_avg}}}.

    Gezählt wird pro Aufgabe (Einträge mit gleicher 'lauf'-ID), nicht pro Versuch."""
    tasks: dict[tuple, dict] = {}
    for e in entries:
        if e.get("api_fehler"):  # Rate-Limit/Netz/Provider sagt nichts über die Qualität des Modells
            continue
        key = (e.get("aufgabenart", e.get("art", "?")), e.get("modell", "?"), e.get("lauf") or id(e))
        t = tasks.setdefault(key, {"ok": False, "versuche": 0, "kosten": 0.0})
        t["versuche"] += 1
        t["ok"] = t["ok"] or bool(e.get("ok"))
        t["kosten"] += float(e.get("kosten") or 0)
    stats: dict[str, dict] = {}
    for (art, model, _), t in tasks.items():
        s = stats.setdefault(art, {}).setdefault(model, {"aufgaben": 0, "erfolge": 0, "versuche": 0, "kosten": 0.0})
        s["aufgaben"] += 1
        s["erfolge"] += int(t["ok"])
        s["versuche"] += t["versuche"]
        s["kosten"] += t["kosten"]
    for art in stats.values():
        for s in art.values():
            s["quote"] = round(s["erfolge"] / s["aufgaben"], 3)
            s["versuche_avg"] = round(s["versuche"] / s["aufgaben"], 2)
            s["kosten_avg"] = round(s["kosten"] / s["aufgaben"], 6)
    return stats


def recommend(stats: dict, art: str, min_quote: float = 0.8, min_tasks: int = 3) -> list[str]:
    """Modelle für eine Aufgabenart sortiert: zuverlässige (Quote ≥ min_quote bei ≥ min_tasks) zuerst,
    darunter die günstigsten; danach der Rest nach Quote."""
    models = stats.get(art, {})
    reliable = [m for m, s in models.items() if s["aufgaben"] >= min_tasks and s["quote"] >= min_quote]
    reliable.sort(key=lambda m: (models[m]["kosten_avg"], models[m]["versuche_avg"]))
    rest = [m for m in models if m not in reliable]
    rest.sort(key=lambda m: (-models[m]["quote"], models[m]["kosten_avg"]))
    return reliable + rest


# ================================================================ Fremdmodell-Aufruf

FENCE_RE = re.compile(r"```([\w+-]*)[^\n]*\n(.*?)```", re.S)
LANG_ALIASES = {"svg": {"svg", "xml"}, "json": {"json", "jsonc"}, "python": {"python", "py"},
                "js": {"js", "javascript", "jsx", "ts", "tsx", "typescript"}, "html": {"html"}}


def extract_result(content: str, art: str) -> str:
    """Ergebnis aus der Modellantwort holen (Codeblock oder rohes SVG/JSON)."""
    blocks = FENCE_RE.findall(content)
    if blocks:
        wanted = LANG_ALIASES.get(art, set())
        matching = [b for lang, b in blocks if lang.lower() in wanted]
        chosen = max(matching or [b for _, b in blocks], key=len)
        return chosen.strip() + "\n"
    if art == "svg":
        m = re.search(r"<svg\b.*</svg>", content, re.S)
        if m:
            return m.group(0) + "\n"
    if art == "json":
        m = re.search(r"[\[{].*[\]}]", content, re.S)
        if m:
            return m.group(0) + "\n"
    return content.strip() + "\n"


def chat(model: str, messages: list[dict], api_key: str, base_url: str = DEFAULT_BASE_URL,
         temperature: float = 0.2, retries: int = 3, session=None, timeout: int = 180) -> dict:
    import requests

    http = session or requests
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "X-Title": "mgt motion-graphics-tools"}
    body = {"model": model, "messages": messages, "temperature": temperature, "usage": {"include": True}}
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            resp = http.post(base_url.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=timeout)
        except Exception as exc:  # Netzwerkfehler
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise ToolError(f"Modell-API nicht erreichbar: {exc}") from exc
        if resp.status_code == 200:
            data = resp.json()
            if data.get("error"):
                raise ToolError(f"Modell {model}: {data['error']}")
            msg = (data.get("choices") or [{}])[0].get("message", {})
            usage = data.get("usage") or {}
            return {"text": msg.get("content") or "", "tokens_ein": usage.get("prompt_tokens", 0),
                    "tokens_aus": usage.get("completion_tokens", 0), "kosten": usage.get("cost", 0) or 0}
        if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code in (401, 403):
            raise ToolError("API-Key abgelehnt. OPENROUTER_API_KEY in .env prüfen.")
        raise ToolError(f"Modell {model}: Fehler {resp.status_code}: {resp.text[:300]}")
    raise ToolError(f"Modell {model} antwortet nicht.")


SYSTEM_PROMPT = ("Du lieferst exakt das angeforderte Ergebnis für ein Motion-Graphics-Projekt. "
                 "Antworte nur mit einem einzigen Codeblock ({art}) ohne Erklärungen.")


def delegate(task: str, art: str, out: Path, models: list[str], api_key: str, attempts: int = 2,
             base_url: str = DEFAULT_BASE_URL, schema: dict | None = None, brand: dict | None = None,
             max_kb: float | None = None, command: str | None = None, task_kind: str | None = None,
             log_path: Path | None = None, system: str | None = None, session=None, cwd: str | None = None) -> dict:
    if art == "auto":
        art = EXT_ART.get(out.suffix.lower(), "text")
    task_kind = task_kind or art
    run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    history = []
    for model in models:
        messages = [{"role": "system", "content": system or SYSTEM_PROMPT.format(art=art)},
                    {"role": "user", "content": task + (f"\n\nGeforderte JSON-Struktur (JSON Schema):\n"
                                                        f"{json.dumps(schema, ensure_ascii=False)}" if schema else "")}]
        for attempt in range(1, attempts + 1):
            t0 = time.time()
            try:
                resp = chat(model, messages, api_key, base_url, session=session)
            except ToolError as exc:
                history.append({"modell": model, "versuch": attempt, "ok": False, "fehler": [str(exc)],
                                "api_fehler": True})
                log_result({"lauf": f"{run_id}-{model}", "aufgabenart": task_kind, "art": art, "modell": model,
                            "versuch": attempt, "ok": False, "api_fehler": True, "fehler": [str(exc)][:3]},
                           log_path)
                break  # API-Fehler: direkt zum nächsten Modell
            result = extract_result(resp["text"], art)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result, encoding="utf-8")
            check = check_content(result, art, out, schema, brand, max_kb, command, cwd)
            entry = {"lauf": f"{run_id}-{model}", "aufgabenart": task_kind, "art": art, "modell": model,
                     "versuch": attempt, "ok": check["ok"], "fehler": check["fehler"][:5],
                     "sekunden": round(time.time() - t0, 2), "tokens_ein": resp["tokens_ein"],
                     "tokens_aus": resp["tokens_aus"], "kosten": resp["kosten"]}
            log_result(entry, log_path)
            history.append(entry)
            if check["ok"]:
                return {"ok": True, "modell": model, "versuche": sum(not h.get("api_fehler") for h in history),
                    "datei": str(out),
                        "verlauf": history, "hinweise": check["hinweise"]}
            messages += [{"role": "assistant", "content": resp["text"]},
                         {"role": "user", "content": "Die automatische Prüfung ist fehlgeschlagen:\n- "
                          + "\n- ".join(check["fehler"][:10])
                          + "\nKorrigiere das und gib das vollständige Ergebnis erneut als einen Codeblock aus."}]
    if out.exists():
        failed = out.with_name(out.name + ".fehlversuch")
        out.replace(failed)
    return {"ok": False, "modell": None, "versuche": len(history), "datei": None, "verlauf": history}


def _api_settings(args) -> tuple[str, str, list[str]]:
    load_dotenv(Path(args.projekt) / ".env")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("MGT_API_KEY", "").strip()
    base = args.api_url or os.environ.get("MGT_API_URL", DEFAULT_BASE_URL)
    models = args.modelle or [m.strip() for m in os.environ.get("MGT_MODELLE", "").split(",") if m.strip()]
    if not key:
        raise ToolError("OPENROUTER_API_KEY fehlt. In .env eintragen (nie committen): OPENROUTER_API_KEY=sk-or-...")
    return key, base, models


def _load_brand(path: str | None):
    if not path:
        return None
    from .brand import parse_brand

    return parse_brand(Path(path))


# ================================================================ CLI

def pruefe_main(args) -> int:
    path = Path(args.datei)
    if not path.exists():
        raise ToolError(f"Datei nicht gefunden: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    schema = read_json(args.schema) if args.schema else None
    res = check_content(text, args.art, path, schema, _load_brand(args.brand), args.max_kb, args.befehl)
    if args.modell:
        log_result({"lauf": args.lauf or datetime.now().strftime("%Y%m%d%H%M%S%f"), "aufgabenart":
                    args.aufgabenart or res["art"], "art": res["art"], "modell": args.modell, "versuch": 1,
                    "ok": res["ok"], "fehler": res["fehler"][:5]}, Path(args.log) if args.log else None)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"{path} ({res['art']}): {'OK' if res['ok'] else 'FEHLER'}")
        for e in res["fehler"]:
            print(f"  - {e}")
        for w in res["hinweise"]:
            print(f"  Hinweis: {w}")
    return 0 if res["ok"] else 1


def delegiere_main(args) -> int:
    key, base, models = _api_settings(args)
    if args.aufgabe_datei:
        task = Path(args.aufgabe_datei).read_text(encoding="utf-8")
    elif args.aufgabe:
        task = args.aufgabe
    else:
        raise ToolError("Bitte --aufgabe \"…\" oder --aufgabe-datei angeben.")
    out = Path(args.aus)
    art = args.art if args.art != "auto" else EXT_ART.get(out.suffix.lower(), "text")
    kind = args.aufgabenart or art
    log_path = Path(args.log) if args.log else None
    if not models:
        models = recommend(statistics(read_log(log_path)), kind)
    if not models:
        raise ToolError("Keine Modelle: --modelle A B … angeben oder MGT_MODELLE=a,b in .env setzen.")
    if args.auto_reihenfolge:
        ranked = recommend(statistics(read_log(log_path)), kind)
        models = [m for m in ranked if m in models] + [m for m in models if m not in ranked]
    schema = read_json(args.schema) if args.schema else None
    print(f"Aufgabe ({kind}) -> {out}; Modelle: {', '.join(models)}", flush=True)
    res = delegate(task, art, out, models, key, args.versuche, base, schema, _load_brand(args.brand),
                   args.max_kb, args.befehl, kind, log_path)
    for h in res["verlauf"]:
        if h["ok"]:
            status = "ok"
        elif h.get("api_fehler"):
            status = "nicht erreichbar (zählt nicht in die Statistik): " + "; ".join(h.get("fehler", []))[:120]
        else:
            status = "Prüfung fehlgeschlagen: " + "; ".join(h.get("fehler", []))[:160]
        print(f"  {h['modell']} Versuch {h['versuch']}: {status}")
    if res["ok"]:
        print(f"ERGEBNIS: {res['datei']} (von {res['modell']}, {res['versuche']} Versuch(e))")
        return 0
    print("ESKALATION: Kein Modell hat die Prüfung bestanden. Aufgabe bitte selbst (Hauptmodell) lösen; "
          f"letzter Versuch liegt unter {out.name}.fehlversuch")
    return 1


def modelle_main(args) -> int:
    stats = statistics(read_log(Path(args.log) if args.log else None))
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if not stats:
        print(f"Noch keine Einträge im Log ({args.log or default_log_path()}).")
        return 0
    for art in sorted(stats):
        if args.aufgabenart and art != args.aufgabenart:
            continue
        print(f"\n{art}:")
        for m in recommend(stats, art):
            s = stats[art][m]
            print(f"  {m:<45} {s['erfolge']}/{s['aufgaben']} ok ({s['quote']:.0%}), "
                  f"ø {s['versuche_avg']} Versuche, ø {s['kosten_avg']:.4f} $")
        best = recommend(stats, art)
        if best and stats[art][best[0]]["quote"] >= 0.8 and stats[art][best[0]]["aufgaben"] >= 3:
            print(f"  Empfehlung: {best[0]}")
        else:
            print("  Empfehlung: noch zu wenig Daten (mind. 3 Aufgaben mit ≥ 80 % Erfolg) – Hauptmodell nutzen.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("pruefe", help="Tool 14a: Ergebnis von Subagent/Fremdmodell prüfen (SVG, JSON-Schema, Code, Tests)")
    p.add_argument("datei", help="zu prüfende Datei")
    p.add_argument("--art", choices=ARTEN, default="auto", help="Art (Standard: aus Dateiendung)")
    p.add_argument("--schema", help="JSON-Schema-Datei (bei JSON)")
    p.add_argument("--brand", help="brand.md: SVG-Farben gegen Brand File prüfen")
    p.add_argument("--max-kb", type=float, help="maximale Dateigröße in KB (SVG)")
    p.add_argument("--befehl", help="zusätzlicher Prüfbefehl, muss mit Exit 0 enden (z. B. \"npx tsc --noEmit\")")
    p.add_argument("--modell", help="Ergebnis für dieses Modell im Log festhalten (z. B. 'claude-haiku-subagent')")
    p.add_argument("--aufgabenart", help="Aufgabenart fürs Log, z. B. 'svg-icon', 'i18n-uebersetzung'")
    p.add_argument("--lauf", help="gleiche Lauf-ID für mehrere Versuche derselben Aufgabe")
    p.add_argument("--log", help="Log-Datei (Standard: ~/.mgt/modell_log.jsonl oder MGT_MODELL_LOG)")
    p.add_argument("--json", action="store_true", help="Ergebnis als JSON")
    p.set_defaults(func=pruefe_main)

    d = sub.add_parser("delegiere", help="Tool 14b: Aufgabe an günstiges Modell (OpenRouter) geben, prüfen, korrigieren lassen, eskalieren")
    d.add_argument("--aufgabe", help="Aufgabentext")
    d.add_argument("--aufgabe-datei", help="Aufgabentext aus Datei")
    d.add_argument("--aus", required=True, help="Zieldatei, z. B. 04_Assets/icon_stern.svg")
    d.add_argument("--art", choices=ARTEN, default="auto", help="Art (Standard: aus Endung von --aus)")
    d.add_argument("--modelle", nargs="*", help="Modelle in Reihenfolge (günstig -> stark), sonst MGT_MODELLE aus .env")
    d.add_argument("--auto-reihenfolge", action="store_true", help="Modelle nach bisheriger Erfolgsstatistik sortieren")
    d.add_argument("--versuche", type=int, default=2, help="Korrektur-Runden pro Modell (Standard 2)")
    d.add_argument("--schema", help="JSON-Schema für das Ergebnis")
    d.add_argument("--brand", help="brand.md für SVG-Farbprüfung")
    d.add_argument("--max-kb", type=float, help="maximale Größe in KB")
    d.add_argument("--befehl", help="zusätzlicher Prüfbefehl nach dem Schreiben (Exit 0 = ok)")
    d.add_argument("--aufgabenart", help="Aufgabenart fürs Log (Standard: Art)")
    d.add_argument("--api-url", help=f"OpenAI-kompatible API (Standard {DEFAULT_BASE_URL} oder MGT_API_URL)")
    d.add_argument("--log", help="Log-Datei (Standard: ~/.mgt/modell_log.jsonl)")
    d.add_argument("--projekt", default=".", help="Projektordner (für .env)")
    d.set_defaults(func=delegiere_main)

    m = sub.add_parser("modelle", help="Tool 14c: Statistik, welches Modell welche Aufgabenart schafft")
    m.add_argument("--aufgabenart", help="nur diese Aufgabenart zeigen")
    m.add_argument("--log", help="Log-Datei (Standard: ~/.mgt/modell_log.jsonl)")
    m.add_argument("--json", action="store_true", help="als JSON")
    m.set_defaults(func=modelle_main)
