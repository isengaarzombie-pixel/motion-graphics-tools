import json

import pytest

from mgtools import delegate as dg
from mgtools.cli import main as cli
from mgtools.common import ToolError

GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#22D3EE"/></svg>'
BRAND = {"farben": ["#22d3ee", "#0f172a"], "verboten": ["#ffa500"], "fonts": []}


# ---------------------------------------------------------------- Prüfungen

def test_svg_checks():
    assert dg.check_svg(GOOD_SVG)[0] == []
    assert any("viewBox" in e for e in dg.check_svg(GOOD_SVG.replace(' viewBox="0 0 24 24"', ""))[0])
    assert any("XML" in e for e in dg.check_svg("<svg><g></svg>")[0])
    assert any("script" in e for e in dg.check_svg(GOOD_SVG.replace("</svg>", "<script>x</script></svg>"))[0])
    assert any("onload" in e for e in dg.check_svg(GOOD_SVG.replace("<circle", '<circle onload="x()"'))[0])
    assert any("Externer" in e for e in dg.check_svg(GOOD_SVG.replace("</svg>", '<image href="https://x.org/a.png"/></svg>'))[0])
    assert any("DOCTYPE" in e for e in dg.check_svg('<!DOCTYPE svg [<!ENTITY a "b">]>' + GOOD_SVG)[0])
    assert any("sichtbaren" in e for e in dg.check_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')[0])
    assert any("<div>" in e for e in dg.check_svg("<div/>")[0])


def test_svg_brand_and_size():
    assert dg.check_svg(GOOD_SVG, BRAND)[0] == []
    bad = GOOD_SVG.replace("#22D3EE", "#FFA500")
    assert any("Verbotene" in e for e in dg.check_svg(bad, BRAND)[0])
    other = GOOD_SVG.replace("#22D3EE", "#123456")
    assert any("Brand" in e for e in dg.check_svg(other, BRAND)[0])
    named = GOOD_SVG.replace('fill="#22D3EE"', 'fill="orange"')
    assert any("Benannte" in e for e in dg.check_svg(named, BRAND)[0])
    assert any("KB" in e for e in dg.check_svg(GOOD_SVG, max_kb=0.01)[0])


def test_schema_validation():
    schema = {"type": "object", "required": ["szenen"], "additionalProperties": False,
              "properties": {"szenen": {"type": "array", "minItems": 1, "items": {
                  "type": "object", "required": ["id", "dauer"],
                  "properties": {"id": {"type": "string", "pattern": "^[a-z_0-9]+$"},
                                 "dauer": {"type": "number", "minimum": 0.5, "maximum": 20},
                                 "typ": {"enum": ["titel", "text"]}}}}}}
    ok = {"szenen": [{"id": "intro", "dauer": 3, "typ": "titel"}]}
    assert dg.validate_schema(ok, schema) == []
    bad = {"szenen": [{"id": "Intro!", "dauer": 30, "typ": "x"}, {"dauer": "3"}], "extra": 1}
    errs = dg.validate_schema(bad, schema)
    text = " ".join(errs)
    for part in ["Muster", "Maximum", "nicht in", "Pflichtfeld 'id'", "Typ str", "unerwartetes Feld"]:
        assert part in text, part
    assert dg.validate_schema(True, {"type": "integer"}) != []
    assert dg.check_json("{kaputt", None)[0]


def test_code_checks():
    assert dg.check_python("x = 1\n")[0] == []
    assert dg.check_python("def f(:\n")[0]
    assert dg.check_js("export const a = () => { return [1, 2]; };", ".mjs")[0] == []
    assert dg.check_js("const a = () => { return [1, 2; };", ".js")[0]
    errs, warns = dg.check_js("export const A = () => <div>{x}</div>;", ".tsx")
    assert errs == [] and warns
    assert dg.check_js("const A = () => <div>{x</div>;", ".tsx")[0]
    assert dg.check_html("<html><body><div><p>Hi</div></body></html>")[0] == []
    assert dg.check_html("<div><span>Hi</div>")[0]
    assert dg.check_text("  ")[0]


def test_check_content_auto_and_command(tmp_path):
    assert dg.check_content(GOOD_SVG, "auto")["art"] == "svg"
    assert dg.check_content('{"a": 1}', "auto")["art"] == "json"
    res = dg.check_content(GOOD_SVG, "svg", command="exit 1")
    assert not res["ok"] and "Exit 1" in res["fehler"][0]


def test_extract_result():
    txt = "Hier:\n```svg\n" + GOOD_SVG + "\n```\nViel Spaß"
    assert dg.extract_result(txt, "svg").strip() == GOOD_SVG
    assert dg.extract_result("blabla " + GOOD_SVG + " ende", "svg").strip() == GOOD_SVG
    assert json.loads(dg.extract_result('Antwort: {"a": [1]} fertig', "json")) == {"a": [1]}
    two = "```json\n{}\n```\n```python\nprint(1)\n```"
    assert dg.extract_result(two, "python").strip() == "print(1)"


def test_cli_pruefe_and_log(tmp_path, capsys):
    f = tmp_path / "icon.svg"
    f.write_text(GOOD_SVG, encoding="utf-8")
    log = tmp_path / "log.jsonl"
    assert cli(["pruefe", str(f), "--modell", "haiku-subagent", "--aufgabenart", "svg-icon", "--log", str(log)]) == 0
    f.write_text(GOOD_SVG.replace(' viewBox="0 0 24 24"', ""), encoding="utf-8")
    assert cli(["pruefe", str(f), "--modell", "haiku-subagent", "--aufgabenart", "svg-icon", "--log", str(log),
                "--json"]) == 1
    entries = dg.read_log(log)
    assert [e["ok"] for e in entries] == [True, False]
    s = (tmp_path / "s.json")
    s.write_text(json.dumps({"type": "object", "required": ["a"]}), encoding="utf-8")
    (tmp_path / "d.json").write_text("{}", encoding="utf-8")
    assert cli(["pruefe", str(tmp_path / "d.json"), "--schema", str(s)]) == 1
    assert cli(["pruefe", str(tmp_path / "fehlt.svg")]) == 2


# ---------------------------------------------------------------- Delegieren (OpenRouter gemockt)

class Resp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._d, self.text = status, data, text

    def json(self):
        return self._d


class FakeAPI:
    """Antworten pro Modell als Liste; jeder Aufruf nimmt die nächste."""

    def __init__(self, answers, status=None):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls, self.status = [], status or {}

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        m = json["model"]
        if m in self.status:
            return Resp(self.status[m], text="err")
        content = self.answers[m].pop(0)
        return Resp(200, {"choices": [{"message": {"content": content}}],
                          "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0002}})


def test_delegate_correction_round(tmp_path):
    api = FakeAPI({"billig/a": ["```svg\n<svg xmlns='http://www.w3.org/2000/svg'><rect width='2' height='2'/></svg>\n```",
                                "```svg\n" + GOOD_SVG + "\n```"]})
    out = tmp_path / "icon.svg"
    log = tmp_path / "log.jsonl"
    res = dg.delegate("Zeichne einen Kreis", "svg", out, ["billig/a"], "KEY", attempts=2, log_path=log,
                      task_kind="svg-icon", session=api)
    assert res["ok"] and res["modell"] == "billig/a" and res["versuche"] == 2
    assert out.read_text(encoding="utf-8").strip() == GOOD_SVG
    second = api.calls[1]["json"]["messages"]
    assert second[-1]["role"] == "user" and "viewBox" in second[-1]["content"]
    assert api.calls[0]["url"].endswith("/chat/completions")
    assert api.calls[0]["headers"]["Authorization"] == "Bearer KEY"
    stats = dg.statistics(dg.read_log(log))
    assert stats["svg-icon"]["billig/a"] == {"aufgaben": 1, "erfolge": 1, "versuche": 2, "kosten": 0.0004,
                                             "quote": 1.0, "versuche_avg": 2.0, "kosten_avg": 0.0004}


def test_delegate_escalates_to_next_model(tmp_path):
    api = FakeAPI({"billig/a": ["kein svg", "immer noch nicht"], "stark/b": [GOOD_SVG]})
    out = tmp_path / "icon.svg"
    res = dg.delegate("Kreis", "svg", out, ["billig/a", "stark/b"], "K", attempts=2, log_path=tmp_path / "l",
                      session=api)
    assert res["ok"] and res["modell"] == "stark/b" and res["versuche"] == 3


def test_delegate_api_error_skips_model(tmp_path, monkeypatch):
    monkeypatch.setattr(dg.time, "sleep", lambda s: None)
    api = FakeAPI({"b": [GOOD_SVG]}, status={"a": 500})
    res = dg.delegate("Kreis", "svg", tmp_path / "x.svg", ["a", "b"], "K", log_path=tmp_path / "l", session=api)
    assert res["ok"] and res["modell"] == "b"
    assert len([c for c in api.calls if c["json"]["model"] == "a"]) == 4  # 1 + 3 Wiederholungen
    assert res["versuche"] == 1
    stats = dg.statistics(dg.read_log(tmp_path / "l"))
    assert "a" not in stats["svg"]  # API-Fehler (z. B. 429 bei Gratis-Modellen) zählen nicht als Misserfolg


def test_delegate_all_fail(tmp_path):
    api = FakeAPI({"a": ["x", "y"]})
    out = tmp_path / "x.svg"
    res = dg.delegate("Kreis", "svg", out, ["a"], "K", attempts=2, log_path=tmp_path / "l", session=api)
    assert not res["ok"] and not out.exists() and (tmp_path / "x.svg.fehlversuch").exists()


def test_delegate_json_with_schema_and_command(tmp_path):
    schema = {"type": "object", "required": ["titel"], "properties": {"titel": {"type": "string"}}}
    api = FakeAPI({"a": ['{"title": "x"}', '```json\n{"titel": "Hallo"}\n```']})
    res = dg.delegate("Übersetze", "json", tmp_path / "en.json", ["a"], "K", schema=schema,
                      command="exit 0", log_path=tmp_path / "l", session=api)
    assert res["ok"] and json.loads((tmp_path / "en.json").read_text(encoding="utf-8")) == {"titel": "Hallo"}
    assert "JSON Schema" in api.calls[0]["json"]["messages"][1]["content"]


def test_api_401(monkeypatch):
    with pytest.raises(ToolError, match="OPENROUTER_API_KEY"):
        dg.chat("a", [], "K", session=FakeAPI({}, status={"a": 401}))


def test_statistics_and_recommend():
    entries = []
    for i in range(4):
        entries.append({"lauf": f"c{i}", "aufgabenart": "svg", "modell": "cheap", "ok": True, "kosten": 0.001})
        entries.append({"lauf": f"m{i}", "aufgabenart": "svg", "modell": "mid", "ok": True, "kosten": 0.01})
        entries.append({"lauf": f"w{i}", "aufgabenart": "svg", "modell": "weak", "ok": i == 0, "kosten": 0.0001})
    entries.append({"lauf": "n", "aufgabenart": "svg", "modell": "new", "ok": True, "kosten": 0})
    stats = dg.statistics(entries)
    assert stats["svg"]["weak"]["quote"] == 0.25
    assert dg.recommend(stats, "svg") == ["cheap", "mid", "new", "weak"]


def test_cli_delegiere_and_modelle(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=test\nMGT_MODELLE=a,b\n", encoding="utf-8")
    for k in ("OPENROUTER_API_KEY", "MGT_MODELLE", "MGT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    api = FakeAPI({"a": ["nix", "nix"], "b": [GOOD_SVG]})
    import requests
    monkeypatch.setattr(requests, "post", api.post)
    log = tmp_path / "log.jsonl"
    rc = cli(["delegiere", "--aufgabe", "Kreis", "--aus", str(tmp_path / "k.svg"), "--projekt", str(tmp_path),
              "--log", str(log), "--aufgabenart", "svg-icon"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ERGEBNIS" in out and "von b" in out
    assert cli(["modelle", "--log", str(log)]) == 0
    assert "svg-icon" in capsys.readouterr().out
    api2 = FakeAPI({"a": ["nix", "nix"], "b": ["nix", "nix"]})
    monkeypatch.setattr(requests, "post", api2.post)
    assert cli(["delegiere", "--aufgabe", "Kreis", "--aus", str(tmp_path / "k2.svg"), "--projekt", str(tmp_path),
                "--log", str(log)]) == 1
    assert "ESKALATION" in capsys.readouterr().out


def test_cli_delegiere_without_key(tmp_path, monkeypatch, capsys):
    for k in ("OPENROUTER_API_KEY", "MGT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert cli(["delegiere", "--aufgabe", "x", "--aus", str(tmp_path / "a.svg"), "--projekt", str(tmp_path)]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
