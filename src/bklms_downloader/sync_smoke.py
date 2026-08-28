"""Offline, package-safe smoke coverage for the resilient sync path."""

from __future__ import annotations

import contextlib
import io
import tempfile
import traceback
from pathlib import Path

import requests

from .crawler import DeepDownloader


def _response(url: str, body: bytes, filename: str) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Length"] = str(len(body))
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response._content = body
    response._content_consumed = True
    return response


class _SyntheticSession:
    def __init__(self) -> None:
        self.calls = 0
        self._outcomes: list[object] = [
            _response("https://lms.hcmut.edu.vn/pluginfile.php/normal", b"first", "first.pdf"),
            requests.Timeout("synthetic timeout"),
            requests.Timeout("synthetic timeout"),
            requests.Timeout("synthetic timeout"),
            _response("https://lms.hcmut.edu.vn/pluginfile.php/after", b"last", "last.pdf"),
        ]

    def get(self, _url: str, **_kwargs) -> requests.Response:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run_synthetic_sync_smoke() -> None:
    """Exercise normal -> timeout -> normal without any LMS request."""
    with tempfile.TemporaryDirectory(prefix="bklms_sync_smoke_") as directory:
        output = Path(directory)
        session = _SyntheticSession()
        events: list[dict] = []
        downloader = DeepDownloader(session=session, output=output, event_callback=events.append)
        # The production crawler writes human-readable console lines.  A
        # windowed executable has no console, so keep this package smoke fully
        # deterministic by capturing those diagnostics internally.
        with contextlib.redirect_stdout(io.StringIO()):
            downloader.download_media_links(
                [
                    ("Synthetic normal resource", "https://lms.hcmut.edu.vn/pluginfile.php/normal"),
                    ("Synthetic timeout resource", "https://lms.hcmut.edu.vn/pluginfile.php/timeout"),
                    ("Synthetic resource after timeout", "https://lms.hcmut.edu.vn/pluginfile.php/after"),
                ],
                output,
                "synthetic sync smoke",
                "",
            )

        assert (output / "01 - first.pdf").read_bytes() == b"first"
        assert (output / "03 - last.pdf").read_bytes() == b"last"
        assert downloader.stats["downloaded"] == 2
        assert downloader.stats["errors"] == 1
        assert session.calls == 5
        assert any(event["event"] == "resource_timeout" for event in events)


def run_sync_runtime_self_test() -> int:
    error_log = Path("sync-self-test-error.log")
    try:
        run_synthetic_sync_smoke()
    except Exception:
        error_log.write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    error_log.unlink(missing_ok=True)
    try:
        print("Synthetic sync: normal -> timeout skipped -> normal after timeout: OK")
    except (AttributeError, OSError, UnicodeError):
        pass
    return 0
