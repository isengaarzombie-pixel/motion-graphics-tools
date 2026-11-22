import base64
import json
import subprocess

import pytest

from conftest import make_alignment, needs_ffmpeg
from mgtools import language
from mgtools.cli import main as cli
from mgtools.common import ToolError
from mgtools.language import check_translation, make_template, merge_alignments, split_text, synthesize

DE = {"titel": "Motion Graphics mit Code", "szenen": {"intro": {"headline": "Hallo {name}!", "sub": "Los geht's"},
                                                      "outro": "Danke fürs Zuschauen"},
      "liste": ["Eins", "Zwei"], "dauer": 3}


def test_make_template_keeps_existing():
    existing = {"titel": "Motion graphics with code", "szenen": {"intro": {"headline": "Hello {name}!"}}}
    tpl, n = make_template(DE, existing)
    assert tpl["titel"] == "Motion graphics with code"
    assert tpl["szenen"]["intro"]["sub"] == "TODO: Los geht's"
    assert tpl["liste"] == ["TODO: Eins", "TODO: Zwei"] and tpl["dauer"] == 3
    assert n == 4


def test_check_translation_finds_problems():
    en = {"titel": "Motion Graphics mit Code", "szenen": {"intro": {"headline": "Hello!", "sub": "TODO: x"},
                                                          "outro": ""}, "liste": ["One", "Two"], "extra": "x"}
    r = check_translation(DE, en)
    assert r["fehlend"] == ["dauer"]
    assert r["todo"] == ["szenen.intro.sub"] and r["leer"] == ["szenen.outro"]
    assert r["platzhalter"] == ["szenen.intro.headline"]
    assert r["unveraendert"] == ["titel"] and r["ueberzaehlig"] == ["extra"]


def test_cli_vorlage_und_pruefen(tmp_path):
    i18n = tmp_path / "05_Code" / "i18n"
    i18n.mkdir(parents=True)
    (i18n / "de.json").write_text(json.dumps(DE), encoding="utf-8")
    assert cli(["sprache", "vorlage", "--projekt", str(tmp_path)]) == 0
    assert cli(["sprache", "pruefen", "--projekt", str(tmp_path)]) == 1
    en = json.loads((i18n / "en.json").read_text())
    en.update({"titel": "Motion graphics with code", "liste": ["One", "Two"]})
    en["szenen"] = {"intro": {"headline": "Hello {name}!", "sub": "Let's go"}, "outro": "Thanks for watching"}
    (i18n / "en.json").write_text(json.dumps(en))
    assert cli(["sprache", "pruefen", "--projekt", str(tmp_path)]) == 0


def test_split_text():
    text = " ".join(f"Satz Nummer {i}." for i in range(200))
    chunks = split_text(text, 500)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 1
    assert " ".join(chunks) == text
    assert split_text("kurz") == ["kurz"]
    long = "wort " * 50
    parts = split_text(long.strip(), 23)
    assert all(len(p) <= 23 for p in parts) and all(w == "wort" for p in parts for w in p.split())


def test_merge_alignments():
    a = make_alignment([{"word": "Hi", "start": 0.0, "end": 0.4}])
    b = make_alignment([{"word": "du", "start": 0.0, "end": 0.3}])
    m = merge_alignments([(a, 0.0), (b, 1.0)])
    assert "".join(m["characters"]) == "Hi du"
    assert m["character_start_times_seconds"][-2] == 1.0


# ---------------------------------------------------------------- ElevenLabs gemockt

@pytest.fixture(scope="module")
def mp3_b64(tmp_path_factory):
    p = tmp_path_factory.mktemp("a") / "t.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.2",
                    "-ac", "1", "-ar", "44100", "-b:a", "128k", str(p)], check=True)
    return base64.b64encode(p.read_bytes()).decode()


class FakeResp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data


class FakeSession:
    """Ahmt requests.post für den with-timestamps-Endpoint nach."""

    def __init__(self, mp3_b64, fail_first=0, status=None):
        self.calls, self.mp3, self.fail_first, self.status = [], mp3_b64, fail_first, status

    def post(self, url, json=None, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "params": params})
        if self.status:
            return FakeResp(self.status, text="denied")
        if len(self.calls) <= self.fail_first:
            return FakeResp(429, text="busy")
        words = [{"word": w, "start": 0.1 + i * 0.3, "end": 0.35 + i * 0.3} for i, w in enumerate(json["text"].split()[:3])]
        return FakeResp(200, {"audio_base64": self.mp3, "alignment": make_alignment(words),
                              "normalized_alignment": make_alignment(words)})


def test_tts_request_payload(mp3_b64):
    s = FakeSession(mp3_b64)
    language.tts_request("Hello world", "voice1", "KEY", "eleven_multilingual_v2", "en", session=s)
    c = s.calls[0]
    assert c["url"].endswith("/text-to-speech/voice1/with-timestamps")
    assert c["headers"]["xi-api-key"] == "KEY" and c["json"]["model_id"] == "eleven_multilingual_v2"
    assert "language_code" not in c["json"]  # multilingual_v2 lehnt language_code ab
    language.tts_request("Hello", "v", "K", "eleven_flash_v2_5", "en", session=s)
    assert s.calls[1]["json"]["language_code"] == "en"


def test_tts_retry_and_errors(mp3_b64, monkeypatch):
    monkeypatch.setattr(language.time, "sleep", lambda s: None)
    s = FakeSession(mp3_b64, fail_first=2)
    assert "audio_base64" in language.tts_request("Hi", "v", "k", "m", session=s)
    assert len(s.calls) == 3
    with pytest.raises(ToolError, match="401"):
        language.tts_request("Hi", "v", "k", "m", session=FakeSession(mp3_b64, status=401))
    with pytest.raises(ToolError, match="400"):
        language.tts_request("Hi", "v", "k", "m", session=FakeSession(mp3_b64, status=400))


@needs_ffmpeg
def test_synthesize_single_and_multi(tmp_path, mp3_b64):
    s = FakeSession(mp3_b64)
    t = synthesize("Hello there friend.", tmp_path / "a" / "voice_raw.mp3", tmp_path / "a" / "timing_raw.json",
                   "v", "k", "eleven_multilingual_v2", "en", project=tmp_path, session=s)
    assert [w["word"] for w in t["words"]] == ["Hello", "there", "friend."]
    assert (tmp_path / "a" / "voice_raw.mp3").stat().st_size > 1000
    log = json.loads((tmp_path / "03_Audio" / "credits_log.json").read_text())
    assert log[0]["menge"] == len("Hello there friend.")

    s2 = FakeSession(mp3_b64)
    text = "One two three. Four five six. Seven eight nine."
    t2 = synthesize(text, tmp_path / "b" / "voice_raw.mp3", tmp_path / "b" / "t.json", "v", "k", "m",
                    project=tmp_path, max_chars=17, session=s2)
    assert len(s2.calls) == 3
    assert s2.calls[1]["json"]["previous_text"] and s2.calls[1]["json"]["next_text"]
    starts = [w["start"] for w in t2["words"]]
    assert starts == sorted(starts) and starts[3] > 1.1  # zweiter Teil um Dauer des ersten versetzt
    from mgtools.finish import video_info
    assert abs(video_info(tmp_path / "b" / "voice_raw.mp3")["dauer"] - 3.6) < 0.2


def test_cli_tts_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    (tmp_path / "t.txt").write_text("Hi")
    assert cli(["sprache", "tts", "--text", str(tmp_path / "t.txt"), "--projekt", str(tmp_path)]) == 2
    assert "ELEVENLABS_API_KEY" in capsys.readouterr().err


@needs_ffmpeg
def test_cli_pipeline_mocked(tmp_path, monkeypatch, mp3_b64):
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=test\nELEVENLABS_VOICE_ID_EN=voiceEN\n")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_EN", raising=False)
    fake = FakeSession(mp3_b64)
    import requests
    monkeypatch.setattr(requests, "post", fake.post)
    (tmp_path / "en.txt").write_text("Welcome back friends.")
    assert cli(["sprache", "pipeline", "--text", str(tmp_path / "en.txt"), "--projekt", str(tmp_path)]) == 0
    assert "voiceEN" in fake.calls[0]["url"]
    d = tmp_path / "03_Audio" / "en"
    for f in ["voice_raw.mp3", "timing_raw.json", "voice.mp3", "timing.json", "schnittliste.json", "timetable.md"]:
        assert (d / f).exists(), f
    scenes = json.loads((tmp_path / "05_Code" / "scenes_en.json").read_text())
    assert scenes["szenen"][0]["words"][0]["word"] == "Welcome"


def test_cli_render_per_language(tmp_path):
    cmd = "echo {lang} {timing} > " + str(tmp_path) + "/{lang}.txt"
    assert cli(["sprache", "render", "--sprachen", "de", "en", "--befehl", cmd]) == 0
    assert (tmp_path / "en.txt").read_text().strip() == "en 03_Audio/en/timing.json"
