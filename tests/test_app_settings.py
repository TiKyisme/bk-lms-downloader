import json
from pathlib import Path

from bklms_downloader.app_settings import AppSettings


def test_missing_settings_uses_default_output(tmp_path: Path):
    default_output = tmp_path / "default"
    settings = AppSettings(tmp_path / "settings.json", default_output=default_output)

    assert settings.last_output_dir == str(default_output)


def test_last_output_dir_saves_loads_and_supports_vietnamese(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    output = tmp_path / "Học tập" / "Học kỳ 1"
    settings = AppSettings(path, default_output=tmp_path / "default")

    settings.set_last_output_dir(output)

    assert AppSettings(path, default_output=tmp_path / "other").last_output_dir == str(output)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "last_output_dir": str(output)}


def test_windows_style_path_is_preserved(tmp_path: Path):
    path = tmp_path / "settings.json"
    windows_path = r"C:\01. Dai_Hoc_Dai_Dai_DT"

    AppSettings(path).set_last_output_dir(windows_path)

    assert AppSettings(path).last_output_dir == windows_path


def test_corrupted_settings_falls_back_to_default(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")

    settings = AppSettings(path, default_output=tmp_path / "safe-default")

    assert settings.last_output_dir == str(tmp_path / "safe-default")


def test_settings_write_is_atomic_and_contains_no_auth_data(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = AppSettings(path)
    settings.set_last_output_dir(tmp_path / "output")

    assert path.is_file()
    assert list(tmp_path.glob(".settings-*.tmp")) == []
    rendered = path.read_text(encoding="utf-8").lower()
    assert "password" not in rendered
    assert "cookie" not in rendered
    assert "session" not in rendered
