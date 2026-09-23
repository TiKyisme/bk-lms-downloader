import sys

from bklms_downloader.lite_runtime import lite_runtime_diagnostics, run_lite_runtime_self_test


def test_lite_runtime_imports_required_modules_without_opening_powerpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "IMPORT FAILED" not in lite_runtime_diagnostics()
    assert run_lite_runtime_self_test() == 0
    assert (tmp_path / "lite-runtime-self-test.log").is_file()


def test_lite_runtime_only_requires_com_on_windows():
    report = lite_runtime_diagnostics()
    assert ("win32com.client" in report) is sys.platform.startswith("win")
