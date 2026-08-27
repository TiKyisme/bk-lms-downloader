from pathlib import Path

import app


def test_ai_runtime_smoke_returns_success(monkeypatch):
    monkeypatch.setattr(app, "_ai_runtime_smoke", lambda: None)

    assert app._run_ai_runtime_smoke() == 0


def test_ai_runtime_smoke_persists_failure_diagnostics(monkeypatch, tmp_path: Path):
    def fail():
        raise ModuleNotFoundError("missing packaged reader")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "_ai_runtime_smoke", fail)

    assert app._run_ai_runtime_smoke() == 1
    diagnostics = (tmp_path / "ai-self-test-error.log").read_text(encoding="utf-8")
    assert "ModuleNotFoundError: missing packaged reader" in diagnostics
