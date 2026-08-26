import logging
from pathlib import Path

import pytest
import requests

from bklms_downloader.app_logging import SensitiveDataFilter, redact_sensitive_text
from bklms_downloader.app_settings import AppSettings
from bklms_downloader.course_store import CourseStore
from bklms_downloader.crawler import DeepDownloader


def response(url: str, body: bytes = b"file", status: int = 200, filename: str = "file.pdf"):
    value = requests.Response()
    value.status_code = status
    value.url = url
    value.headers["Content-Type"] = "application/pdf"
    value.headers["Content-Length"] = str(len(body))
    value.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    value._content = body
    value._content_consumed = True
    return value


class SequenceSession:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_fetch_retries_transient_failure_then_succeeds(monkeypatch, tmp_path: Path):
    session = SequenceSession([requests.ConnectionError("reset"), response("https://lms.hcmut.edu.vn/file")])
    downloader = DeepDownloader(session=session, output=tmp_path)
    sleeps = []
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", sleeps.append)

    result = downloader.fetch("https://lms.hcmut.edu.vn/file")

    assert result.status_code == 200
    assert session.calls == 2
    assert sleeps == [0.4]


def test_fetch_exhausts_transient_retries(monkeypatch, tmp_path: Path):
    session = SequenceSession([requests.Timeout(), requests.Timeout(), requests.Timeout()])
    downloader = DeepDownloader(session=session, output=tmp_path)
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", lambda _delay: None)

    with pytest.raises(requests.Timeout):
        downloader.fetch("https://lms.hcmut.edu.vn/file")
    assert session.calls == 3


def test_fetch_retries_server_error_but_not_client_error(monkeypatch, tmp_path: Path):
    server_session = SequenceSession(
        [response("https://lms.hcmut.edu.vn/file", status=503), response("https://lms.hcmut.edu.vn/file")]
    )
    downloader = DeepDownloader(session=server_session, output=tmp_path)
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", lambda _delay: None)
    assert downloader.fetch("https://lms.hcmut.edu.vn/file").status_code == 200
    assert server_session.calls == 2

    client_session = SequenceSession([response("https://lms.hcmut.edu.vn/file", status=403)])
    with pytest.raises(requests.HTTPError):
        DeepDownloader(session=client_session, output=tmp_path).fetch("https://lms.hcmut.edu.vn/file")
    assert client_session.calls == 1


def test_same_filename_from_different_sources_is_kept_and_partial_failure_is_cleaned(tmp_path: Path):
    downloader = DeepDownloader(session=requests.Session(), output=tmp_path)
    first = response("https://lms.hcmut.edu.vn/pluginfile.php/1/a", b"one", filename="guide.pdf")
    second = response("https://lms.hcmut.edu.vn/pluginfile.php/2/b", b"two!", filename="guide.pdf")
    downloader.save_response_file(first, tmp_path, "guide", first.url, "test")
    downloader.save_response_file(second, tmp_path, "guide", second.url, "test")

    assert sorted(path.name for path in tmp_path.glob("*.pdf")) == ["guide (2).pdf", "guide.pdf"]

    target = tmp_path / "broken.pdf"
    target.write_bytes(b"valid")
    broken = response("https://lms.hcmut.edu.vn/pluginfile.php/3/c", b"new-file", filename="broken.pdf")

    def fail_chunks(_chunk_size):
        raise OSError("disk write failed")
        yield b""

    broken.iter_content = fail_chunks  # type: ignore[method-assign]
    with pytest.raises(OSError):
        downloader.save_response_file(broken, tmp_path, "broken", broken.url, "test")
    assert target.read_bytes() == b"valid"
    assert not (tmp_path / "broken.pdf.part").exists()


def test_corrupt_settings_and_courses_are_backed_up(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("bad settings", encoding="utf-8")
    AppSettings(settings_path, default_output=tmp_path / "default")
    assert list(tmp_path.glob("settings.corrupt-*.json"))

    courses_path = tmp_path / "courses.json"
    courses_path.write_text("bad courses", encoding="utf-8")
    CourseStore(courses_path)
    assert list(tmp_path.glob("courses.corrupt-*.json"))


def test_logging_redacts_cookies_and_session_values():
    text = "Cookie: MoodleSession=secret; Authorization: Bearer hidden token=abc"
    redacted = redact_sensitive_text(text)
    assert "secret" not in redacted
    assert "hidden" not in redacted
    assert "abc" not in redacted

    record = logging.LogRecord("test", logging.INFO, "", 0, text, (), None)
    SensitiveDataFilter().filter(record)
    assert "secret" not in record.getMessage()
