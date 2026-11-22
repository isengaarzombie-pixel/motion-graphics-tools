import json
import subprocess

import pytest
from PIL import Image

from conftest import make_video, needs_ffmpeg, silence, tone
from mgtools.cli import main as cli
from mgtools.common import write_wav
from mgtools.finish import check_spec, measure_loudness, parse_loudnorm, video_info
from mgtools.multiformat import reframe, reframe_filter, render_loop
from mgtools.storyboard import build_sheet, overlay_safe_area

pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def quiet_video(tmp_path_factory):
    d = tmp_path_factory.mktemp("v")
    return make_video(d / "render.mp4", dur=4.0, volume_db=-30)


# ---------------------------------------------------------------- Storyboard

def test_safe_area_overlay_marks_bottom_right():
    im = Image.new("RGB", (1080, 1920), (0, 0, 0))
    out = overlay_safe_area(im, "shorts")
    assert out.getpixel((540, 1900))[0] > 50  # unten rot
    assert out.getpixel((1070, 900))[0] > 50  # rechts rot
    assert out.getpixel((540, 900))[0] == 0  # Mitte frei


def test_build_sheet_grid(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"{i + 1:02d}_szene_{i + 1:02d}.png"
        Image.new("RGB", (1920, 1080), (40 * i, 80, 120)).save(p)
        paths.append(p)
    sheet = build_sheet(paths, columns=3, thumb_width=300, captions={"szene_02": "Hallo Welt"}, title="Test")
    assert sheet.width == 3 * 300 + 4 * 24
    assert sheet.height > 2 * 169


def test_cli_storyboard_from_video(quiet_video, tmp_path):
    scenes = {"fps": 30, "szenen": [{"id": "a", "start": 0, "end": 2, "text": "Eins"},
                                    {"id": "b", "start": 2, "end": 4, "text": "Zwei"}]}
    (tmp_path / "scenes.json").write_text(json.dumps(scenes), encoding="utf-8")
    out = tmp_path / "sb.png"
    assert cli(["storyboard", "--video", str(quiet_video), "--szenen", str(tmp_path / "scenes.json"),
                "--frames-ordner", str(tmp_path / "frames"), "--aus", str(out), "--safe-area", "16:9"]) == 0
    assert out.exists() and len(list((tmp_path / "frames").glob("*.png"))) == 2


def test_cli_storyboard_empty_folder(tmp_path, capsys):
    (tmp_path / "leer").mkdir()
    assert cli(["storyboard", str(tmp_path / "leer"), "--aus", str(tmp_path / "x.png")]) == 2


# ---------------------------------------------------------------- Finish

def test_video_info_and_spec(quiet_video):
    info = video_info(quiet_video)
    assert info["video"]["breite"] == 1920 and info["video"]["fps"] == 30
    assert check_spec(info, "16:9", 30) == []
    probs = check_spec(info, "9:16", 25)
    assert any("Auflösung" in p for p in probs) and any("Bildrate" in p for p in probs)


def test_parse_loudnorm():
    txt = 'xx [Parsed_loudnorm_0 @ 0x1]\n{\n "input_i" : "-23.0",\n "input_tp" : "-5.0",\n' \
          ' "input_lra" : "1.0",\n "input_thresh" : "-33.0",\n "target_offset" : "0.1"\n}\n'
    assert parse_loudnorm(txt)["input_i"] == "-23.0"


def test_finish_normalizes_to_minus_14(quiet_video, tmp_path, capsys):
    before = measure_loudness(quiet_video)
    assert before["lufs"] < -25
    out = tmp_path / "final.mp4"
    assert cli(["finish", str(quiet_video), "--aus", str(out)]) == 0
    after = measure_loudness(out)
    assert abs(after["lufs"] - (-14)) <= 1.0
    assert after["true_peak"] <= -0.5
    info = video_info(out)
    assert info["video"]["codec"] == "h264" and info["audio"]["codec"] == "aac"
    assert "fertig für den Upload" in capsys.readouterr().out


def test_finish_check_only_fails_for_quiet(quiet_video):
    assert cli(["finish", str(quiet_video), "--nur-pruefen"]) == 1


def test_finish_with_music(quiet_video, tmp_path):
    music = write_wav(tmp_path / "musik.wav", tone(1.5, 220, 0.3))
    out = tmp_path / "final_musik.mp4"
    assert cli(["finish", str(quiet_video), "--aus", str(out), "--musik", str(music)]) == 0
    assert abs(measure_loudness(out)["lufs"] + 14) <= 1.0
    assert abs(video_info(out)["dauer"] - 4.0) < 0.2


def test_finish_reencodes_wrong_codec(tmp_path):
    src = make_video(tmp_path / "in.mp4", w=640, h=360, dur=1.5, codec="mpeg4")
    out = tmp_path / "out.mp4"
    cli(["finish", str(src), "--aus", str(out)])
    assert video_info(out)["video"]["codec"] == "h264"


def test_finish_no_audio(tmp_path):
    src = make_video(tmp_path / "stumm.mp4", dur=1, audio=False)
    assert cli(["finish", str(src), "--aus", str(tmp_path / "o.mp4")]) == 1


# ---------------------------------------------------------------- Multiformat

@pytest.mark.parametrize("mode", ["blur", "crop", "pad"])
def test_reframe_to_vertical(quiet_video, tmp_path, mode):
    out = reframe(quiet_video, tmp_path / f"v_{mode}.mp4", "9:16", mode, fps=30)
    info = video_info(out)
    assert (info["video"]["breite"], info["video"]["hoehe"]) == (1080, 1920)
    assert info["audio"] is not None and abs(info["dauer"] - 4.0) < 0.2


def test_reframe_vertical_to_horizontal(tmp_path):
    src = make_video(tmp_path / "v.mp4", w=1080, h=1920, dur=1)
    out = reframe(src, tmp_path / "h.mp4", "16:9", "blur")
    assert video_info(out)["video"]["breite"] == 1920


def test_reframe_filter_focus():
    f = reframe_filter("crop", 1080, 1920, focus_x=0.2)
    assert "(iw-1080)*0.2" in f


def test_cli_formate_umwandeln(quiet_video, tmp_path):
    assert cli(["formate", "umwandeln", str(quiet_video), "--formate", "9:16", "1:1", "--ordner", str(tmp_path)]) == 0
    assert (tmp_path / "render_9x16.mp4").exists() and (tmp_path / "render_1x1.mp4").exists()


def test_render_loop(tmp_path):
    cmds = render_loop("echo {name} {breite}x{hoehe} > " + str(tmp_path) + "/{name}.txt",
                       [{"name": "9x16", "breite": 1080, "hoehe": 1920}])
    assert (tmp_path / "9x16.txt").read_text(encoding="utf-8").strip() == "9x16 1080x1920"
    assert cli(["formate", "render", "--formate", "16:9", "9:16", "--probe", "--befehl", "npx x {name}"]) == 0
    assert cli(["formate", "render", "--befehl", "exit 3"]) == 2
