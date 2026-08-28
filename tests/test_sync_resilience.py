from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
import requests

from bklms_downloader.config import (
    MAX_REQUEST_ATTEMPTS,
    REQUEST_CONNECT_TIMEOUT,
    REQUEST_READ_TIMEOUT,
    RESOURCE_OPEN_DEADLINE,
)
from bklms_downloader.crawler import AuthenticationError, DeepDownloader, ResourceTimeout, SyncCancelled
from bklms_downloader.gui import App
from bklms_downloader.models import Course, CourseSyncResult, SyncBatchResult
from bklms_downloader.sync_manager import SyncManager
from bklms_downloader.sync_smoke import run_synthetic_sync_smoke


def make_response(
    url: str,
    body: bytes = b"file",
    *,
    filename: str = "file.pdf",
    content_length: int | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Length"] = str(content_length if content_length is not None else len(body))
    response._content = body
    response._content_consumed = True
    return response


class RecordingSession:
    def __init__(self, outcomes: list[object]):
        self.outcomes = iter(outcomes)
        self.calls: list[dict] = []

    def get(self, _url: str, **kwargs):
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_timeout_uses_separate_socket_limits_and_capped_retries(monkeypatch, tmp_path: Path):
    session = RecordingSession([requests.ReadTimeout("slow")] * MAX_REQUEST_ATTEMPTS)
    events: list[dict] = []
    downloader = DeepDownloader(session=session, output=tmp_path, event_callback=events.append)
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", lambda _delay: None)

    with pytest.raises(ResourceTimeout):
        downloader.fetch("https://lms.hcmut.edu.vn/pluginfile.php/slow", resource_name="Tài liệu chậm")

    assert len(session.calls) == MAX_REQUEST_ATTEMPTS
    assert all(call["stream"] is True for call in session.calls)
    assert all(call["timeout"] == (REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT) for call in session.calls)
    assert [event["event"] for event in events].count("resource_retry") == MAX_REQUEST_ATTEMPTS - 1
    assert events[-1]["event"] == "resource_timeout"
    assert "Tài liệu chậm" in events[-1]["message"]


def test_opening_deadline_prevents_multi_minute_retry_budget(monkeypatch, tmp_path: Path):
    clock = [0.0]

    class DeadlineSession:
        calls = 0

        def get(self, _url: str, **kwargs):
            type(self).calls += 1
            connect, read = kwargs["timeout"]
            # Simulate a worst-case connect followed by an inactive read.
            clock[0] += connect + read
            raise requests.Timeout("slow")

    monkeypatch.setattr("bklms_downloader.crawler.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", lambda _delay: None)

    with pytest.raises(ResourceTimeout):
        DeepDownloader(session=DeadlineSession(), output=tmp_path).fetch(
            "https://lms.hcmut.edu.vn/pluginfile.php/dead",
            resource_name="Tài liệu không phản hồi",
        )

    assert RESOURCE_OPEN_DEADLINE <= 45
    assert DeadlineSession.calls == 2
    assert clock[0] < 60


def test_login_redirect_is_not_treated_as_a_skippable_resource(tmp_path: Path):
    login = make_response("https://lms.hcmut.edu.vn/login/index.php", b"login", filename="login.html")
    session = RecordingSession([login])

    with pytest.raises(AuthenticationError):
        DeepDownloader(session=session, output=tmp_path).fetch(
            "https://lms.hcmut.edu.vn/pluginfile.php/protected",
            resource_name="Tài liệu cần đăng nhập",
        )

    assert len(session.calls) == 1


def test_offline_sync_smoke_proves_resource_after_timeout_is_processed():
    run_synthetic_sync_smoke()


def test_timed_out_resource_is_skipped_and_later_resources_continue(monkeypatch, tmp_path: Path):
    session = RecordingSession(
        [
            make_response("https://lms.hcmut.edu.vn/pluginfile.php/normal", b"first", filename="first.pdf"),
            requests.Timeout("dead resource"),
            requests.Timeout("dead resource"),
            requests.Timeout("dead resource"),
            make_response("https://lms.hcmut.edu.vn/pluginfile.php/after", b"last", filename="last.pdf"),
        ]
    )
    events: list[dict] = []
    downloader = DeepDownloader(session=session, output=tmp_path, event_callback=events.append)
    monkeypatch.setattr("bklms_downloader.crawler.time.sleep", lambda _delay: None)

    downloader.download_media_links(
        [
            ("Tài liệu bình thường", "https://lms.hcmut.edu.vn/pluginfile.php/normal"),
            ("Tài liệu lỗi", "https://lms.hcmut.edu.vn/pluginfile.php/timeout"),
            ("Tài liệu sau lỗi", "https://lms.hcmut.edu.vn/pluginfile.php/after"),
        ],
        tmp_path,
        "test",
        "",
    )

    assert (tmp_path / "01 - first.pdf").read_bytes() == b"first"
    assert (tmp_path / "03 - last.pdf").read_bytes() == b"last"
    assert downloader.stats["downloaded"] == 2
    assert downloader.stats["errors"] == 1
    assert any(
        event["event"] == "resource_timeout" and "Tài liệu lỗi" in event["message"]
        for event in events
    )


def test_cancelled_transfer_cleans_part_and_keeps_existing_file(tmp_path: Path):
    cancel_event = Event()
    downloader = DeepDownloader(
        session=RecordingSession([]),
        output=tmp_path,
        force=True,
        cancel_event=cancel_event,
    )
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"already complete")
    response = make_response(
        "https://lms.hcmut.edu.vn/pluginfile.php/replacement",
        filename="existing.pdf",
    )

    def chunks(_chunk_size: int):
        yield b"partial"
        cancel_event.set()
        yield b"must not replace"

    response.iter_content = chunks  # type: ignore[method-assign]

    with pytest.raises(SyncCancelled):
        downloader.save_response_file(response, tmp_path, "existing", response.url, "test")

    assert target.read_bytes() == b"already complete"
    assert not (tmp_path / "existing.pdf.part").exists()


def test_active_large_stream_is_allowed_to_make_progress(monkeypatch, tmp_path: Path):
    downloader = DeepDownloader(session=RecordingSession([]), output=tmp_path)
    response = make_response(
        "https://lms.hcmut.edu.vn/pluginfile.php/large",
        b"data",
        filename="large.pdf",
        content_length=10 * 1024 * 1024,
    )
    clock_values = iter([0.0, 0.0, 149.0, 149.0])
    monkeypatch.setattr("bklms_downloader.crawler.time.monotonic", lambda: next(clock_values))

    saved = downloader.save_response_file(response, tmp_path, "large", response.url, "test")

    assert saved is not None
    assert saved.read_bytes() == b"data"


def test_stream_total_deadline_cleans_partial_file(monkeypatch, tmp_path: Path):
    downloader = DeepDownloader(session=RecordingSession([]), output=tmp_path)
    response = make_response(
        "https://lms.hcmut.edu.vn/pluginfile.php/dribble",
        b"x",
        filename="dribble.pdf",
        content_length=1,
    )
    clock_values = iter([0.0, 0.0, 121.0])
    monkeypatch.setattr("bklms_downloader.crawler.time.monotonic", lambda: next(clock_values))

    with pytest.raises(ResourceTimeout):
        downloader.save_response_file(response, tmp_path, "dribble", response.url, "test")

    assert not (tmp_path / "dribble.pdf").exists()
    assert not (tmp_path / "dribble.pdf.part").exists()


class BatchDownloader:
    outcomes: dict[str, object] = {}
    calls: list[str] = []

    def __init__(self, *, output, **_kwargs):
        self.output = Path(output)
        self.root_course_name = None
        self.stats = {"downloaded": 0, "skipped": 0, "skipped_video": 0, "pages_saved": 0, "errors": 0}

    def crawl_course(self, url: str, _output: Path, depth: int = 0):
        assert depth == 0
        type(self).calls.append(url)
        outcome = type(self).outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        self.stats.update(outcome)
        return self.output / "Course"


def test_cancelled_batch_stops_before_next_course_and_emits_completion(tmp_path: Path):
    first = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", str(tmp_path / "one"))
    second = Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", str(tmp_path / "two"))
    third = Course("3", "https://lms.hcmut.edu.vn/course/view.php?id=3", str(tmp_path / "three"))
    BatchDownloader.calls = []
    BatchDownloader.outcomes = {
        first.url: {"downloaded": 1},
        second.url: SyncCancelled("cancel"),
        third.url: {"downloaded": 1},
    }
    events: list[dict] = []

    batch = SyncManager(downloader_factory=BatchDownloader).sync_courses(
        [first, second, third],
        requests.Session(),
        events.append,
        cancel_event=Event(),
    )

    assert batch.cancelled
    assert [result.course_id for result in batch.results] == [first.id]
    assert BatchDownloader.calls == [first.url, second.url]
    assert events[-1]["event"] == "sync_all_complete"


def test_pre_cancelled_batch_does_not_start_a_new_course(tmp_path: Path):
    course = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", str(tmp_path / "one"))
    BatchDownloader.calls = []
    BatchDownloader.outcomes = {course.url: {"downloaded": 1}}
    cancel_event = Event()
    cancel_event.set()

    batch = SyncManager(downloader_factory=BatchDownloader).sync_courses(
        [course], requests.Session(), cancel_event=cancel_event
    )

    assert batch.cancelled
    assert not batch.results
    assert BatchDownloader.calls == []


class FakeWidget:
    def __init__(self):
        self.state = "normal"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)


class FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def bare_sync_app() -> App:
    app = App.__new__(App)
    app.syncing = True
    app.sync_cancel_event = Event()
    app.sync_started_at = 1.0
    app.sync_elapsed_var = FakeVar()
    app.progress = type("Progress", (), {"set": lambda _self, _value: None})()
    app.overall_var = FakeVar()
    app.current_course_var = FakeVar()
    app.cancel_sync_btn = FakeWidget()
    for name in (
        "login_btn",
        "add_btn",
        "import_btn",
        "edit_btn",
        "delete_btn",
        "open_btn",
        "tools_btn",
        "sync_selected_btn",
        "sync_all_btn",
    ):
        setattr(app, name, FakeWidget())
    app._refresh_courses = lambda: None
    app._set_login_status = lambda *_args: None
    app._set_summary_message = lambda message: setattr(app, "summary", message)
    app._set_summary_counts = lambda *_args: setattr(app, "summary", "counts")
    return app


@pytest.mark.parametrize(
    ("batch", "expected"),
    [
        (SyncBatchResult([]), "counts"),
        (SyncBatchResult([CourseSyncResult("1", "url", "course", None, errors=1, status="error")]), "Hoàn tất với 1 lỗi"),
        (SyncBatchResult([], cancelled=True), "Đã hủy đồng bộ."),
    ],
)
def test_gui_sync_state_returns_to_idle_after_success_error_or_cancel(monkeypatch, batch, expected):
    app = bare_sync_app()
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showinfo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("bklms_downloader.gui.messagebox.showwarning", lambda *_args, **_kwargs: None)

    App._complete_sync(app, batch, total=1)

    assert not app.syncing
    assert app.sync_cancel_event is None
    assert app.cancel_sync_btn.state == "disabled"
    assert expected in app.summary
