import json
from pathlib import Path

import pytest

from bklms_downloader.app_settings import ONBOARDING_VERSION, AppSettings


def test_missing_settings_uses_default_output(tmp_path: Path):
    default_output = tmp_path / "default"
    settings = AppSettings(tmp_path / "settings.json", default_output=default_output)

    assert settings.last_output_dir == str(default_output)
    assert settings.is_new_profile
    assert settings.should_auto_show_onboarding()


def test_last_output_dir_saves_loads_and_supports_vietnamese(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    output = tmp_path / "Học tập" / "Học kỳ 1"
    settings = AppSettings(path, default_output=tmp_path / "default")

    settings.set_last_output_dir(output)

    assert AppSettings(path, default_output=tmp_path / "other").last_output_dir == str(output)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 2,
        "last_output_dir": str(output),
        "onboarding_completed_version": 0,
    }


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
    assert settings.is_new_profile
    assert settings.should_auto_show_onboarding()


def test_legacy_settings_are_migrated_without_auto_onboarding(tmp_path: Path):
    path = tmp_path / "settings.json"
    output = tmp_path / "legacy-output"
    path.write_text(
        json.dumps({"schema_version": 1, "last_output_dir": str(output)}),
        encoding="utf-8",
    )

    settings = AppSettings(path, default_output=tmp_path / "default")

    assert settings.last_output_dir == str(output)
    assert not settings.is_new_profile
    assert not settings.should_auto_show_onboarding()
    assert json.loads(path.read_text(encoding="utf-8"))["onboarding_completed_version"] == ONBOARDING_VERSION


def test_onboarding_completion_is_persisted_and_manual_replay_does_not_reset(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = AppSettings(path, default_output=tmp_path / "default")

    settings.mark_onboarding_completed()

    reloaded = AppSettings(path, default_output=tmp_path / "other")
    assert reloaded.onboarding_completed_version == ONBOARDING_VERSION
    assert not reloaded.should_auto_show_onboarding()
    reloaded.mark_onboarding_completed()
    assert AppSettings(path).onboarding_completed_version == ONBOARDING_VERSION


def test_onboarding_skip_uses_the_same_completed_marker(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = AppSettings(path)

    # The UI marks both “Hoàn tất” and “Bỏ qua” through this harmless boundary.
    settings.mark_onboarding_completed()

    assert not AppSettings(path).should_auto_show_onboarding()


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
    assert "onboarding_completed_version" in rendered


def test_setting_rolls_back_when_atomic_replace_fails(tmp_path: Path, monkeypatch):
    path = tmp_path / "settings.json"
    old_output = tmp_path / "old"
    settings = AppSettings(path, default_output=old_output)
    settings.set_last_output_dir(old_output)
    original_bytes = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("replace blocked")

    monkeypatch.setattr("bklms_downloader.app_settings.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace blocked"):
        settings.set_last_output_dir(tmp_path / "new")

    assert settings.last_output_dir == str(old_output)
    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".settings-*.tmp")) == []
