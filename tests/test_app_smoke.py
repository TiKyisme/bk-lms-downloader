from pathlib import Path

import bklms_downloader.ai_prepare as ai_prepare


def test_ai_runtime_smoke_returns_success(monkeypatch):
    monkeypatch.setattr(ai_prepare, "_ai_runtime_self_test", lambda: None)

    assert ai_prepare.run_ai_runtime_self_test() == 0


def test_ai_runtime_smoke_persists_failure_diagnostics(monkeypatch, tmp_path: Path):
    def fail():
        raise ModuleNotFoundError("missing packaged reader")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ai_prepare, "_ai_runtime_self_test", fail)

    assert ai_prepare.run_ai_runtime_self_test() == 1
    diagnostics = (tmp_path / "ai-self-test-error.log").read_text(encoding="utf-8")
    assert "ModuleNotFoundError: missing packaged reader" in diagnostics
