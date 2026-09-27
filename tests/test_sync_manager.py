from pathlib import Path

import requests

from bklms_downloader.course_store import CourseStore
from bklms_downloader.models import Course
from bklms_downloader.sync_manager import SyncManager


def course_url(course_id: int) -> str:
    return f"https://lms.hcmut.edu.vn/course/view.php?id={course_id}"


class FakeDownloader:
    calls: list[tuple[str, object]] = []
    outcomes: dict[str, object] = {}

    def __init__(self, *, session, output, **_kwargs):
        self.session = session
        self.output = Path(output)
        self.stats = {
            "downloaded": 0,
            "skipped": 0,
            "skipped_video": 0,
            "pages_saved": 0,
            "errors": 0,
        }
        self.root_course_name = None

    def crawl_course(self, url, _output, depth=0):
        assert depth == 0
        type(self).calls.append((url, self.session))
        outcome = type(self).outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        self.stats.update(outcome["stats"])
        self.root_course_name = outcome.get("name", "")
        destination = self.output / outcome.get("folder", "Course")
        destination.mkdir(parents=True, exist_ok=True)
        self.manifest = outcome.get("manifest", [])
        return destination


def configure_fake(*outcomes):
    FakeDownloader.calls = []
    FakeDownloader.outcomes = {
        course_url(index + 1): outcome for index, outcome in enumerate(outcomes)
    }


def test_sync_manager_runs_sequentially_reuses_session_and_aggregates(tmp_path: Path):
    configure_fake(
        {"name": "Mạng máy tính (CO3094)", "stats": {"downloaded": 3, "skipped": 14, "skipped_video": 1}},
        {"name": "PPL (CO3005)", "stats": {"downloaded": 0, "skipped": 9}},
    )
    store = CourseStore(tmp_path / "courses.json")
    first = store.add(course_url(1), tmp_path / "one")
    second = store.add(course_url(2), tmp_path / "two")
    events = []
    session = requests.Session()

    batch = SyncManager(store, FakeDownloader).sync_courses(
        [first, second], session, events.append
    )

    assert [url for url, _session in FakeDownloader.calls] == [course_url(1), course_url(2)]
    assert all(call_session is session for _url, call_session in FakeDownloader.calls)
    assert [result.status for result in batch.results] == ["success", "up_to_date"]
    assert (batch.downloaded, batch.skipped, batch.skipped_video, batch.errors) == (3, 23, 1, 0)
    assert [event["event"] for event in events if event["event"] != "crawler_event"] == [
        "course_sync_start",
        "course_sync_complete",
        "course_sync_start",
        "course_sync_complete",
        "sync_all_complete",
    ]
    saved = CourseStore(store.path).list()
    assert saved[0].code == "CO3094"
    assert saved[0].last_downloaded == 3
    assert saved[1].last_status == "up_to_date"


def test_failed_course_does_not_stop_next_course(tmp_path: Path):
    configure_fake(
        RuntimeError("HTTP error"),
        {"name": "Course two", "stats": {"downloaded": 2}},
    )
    store = CourseStore(tmp_path / "courses.json")
    first = store.add(course_url(1), tmp_path / "one")
    second = store.add(course_url(2), tmp_path / "two")

    batch = SyncManager(store, FakeDownloader).sync_courses([first, second], requests.Session())

    assert [url for url, _session in FakeDownloader.calls] == [course_url(1), course_url(2)]
    assert [result.status for result in batch.results] == ["error", "success"]
    assert batch.errors == 1
    assert CourseStore(store.path).get(first.id).last_status == "error"
    assert CourseStore(store.path).get(second.id).last_status == "success"


def test_expired_session_stops_the_remaining_batch(tmp_path: Path):
    configure_fake(
        RuntimeError("Phiên đăng nhập BK-LMS chưa hợp lệ hoặc đã hết hạn. Hãy đăng nhập lại."),
        {"name": "Should not run", "stats": {"downloaded": 2}},
    )
    store = CourseStore(tmp_path / "courses.json")
    first = store.add(course_url(1), tmp_path / "one")
    second = store.add(course_url(2), tmp_path / "two")

    batch = SyncManager(store, FakeDownloader).sync_courses([first, second], requests.Session())

    assert batch.authentication_error
    assert len(batch.results) == 1
    assert [url for url, _session in FakeDownloader.calls] == [course_url(1)]


def test_recoverable_resource_error_returns_partial_and_keeps_safe_details(tmp_path: Path):
    configure_fake({
        "name": "Course one",
        "stats": {"downloaded": 44, "errors": 1},
        "manifest": [{
            "status": "error",
            "context": "Course one > Week 4 > Assignment 4",
            "source": "https://lms.hcmut.edu.vn/pluginfile.php/4?token=secret",
            "error": "404 Client Error: Not Found; Authorization: Bearer auth-secret Cookie: sessionid=cookie-secret",
        }],
    })
    store = CourseStore(tmp_path / "courses.json")
    course = store.add(course_url(1), tmp_path / "one")

    batch = SyncManager(store, FakeDownloader).sync_courses([course], requests.Session())

    result = batch.results[0]
    assert result.status == "partial"
    assert result.downloaded == 44
    assert result.errors == 1
    assert batch.synced_courses == 1
    assert batch.partial_errors == 1
    assert batch.fatal_course_failures == 0
    assert result.resource_failures[0].title == "Assignment 4"
    assert "token" not in result.resource_failures[0].source
    assert "auth-secret" not in result.resource_failures[0].reason
    assert "cookie-secret" not in result.resource_failures[0].reason
    assert CourseStore(store.path).get(course.id).last_status == "partial"


def test_partial_first_course_counts_complete_before_second_succeeds(tmp_path: Path):
    configure_fake(
        {"stats": {"downloaded": 44, "errors": 1}},
        {"stats": {"downloaded": 2}},
    )
    first = Course("one", course_url(1), str(tmp_path / "one"), name="One")
    second = Course("two", course_url(2), str(tmp_path / "two"), name="Two")

    batch = SyncManager(downloader_factory=FakeDownloader).sync_courses(
        [first, second], requests.Session()
    )

    assert [result.status for result in batch.results] == ["partial", "success"]
    assert batch.synced_courses == 2
    assert batch.partial_errors == 1
    assert batch.fatal_course_failures == 0


def test_retry_after_partial_skips_successful_and_retries_failed_resource(tmp_path: Path):
    course = Course("one", course_url(1), str(tmp_path / "one"), name="One")
    completed_files = {"file.pdf": b"already downloaded"}
    attempts = 0

    class RetryDownloader:
        def __init__(self, *, output, **_kwargs):
            self.output = Path(output)
            self.root_course_name = "One"
            self.stats = {"downloaded": 0, "skipped": 0, "skipped_video": 0, "pages_saved": 0, "errors": 0}
            self.manifest = []

        def crawl_course(self, _url, _output, depth=0):
            nonlocal attempts
            assert depth == 0
            destination = self.output / "One"
            destination.mkdir(parents=True, exist_ok=True)
            if "file.pdf" in completed_files:
                self.stats["skipped"] = 1
            attempts += 1
            if attempts == 1:
                self.stats["errors"] = 1
                self.manifest = [{"status": "error", "context": "Broken attachment", "source": course_url(9), "error": "404"}]
            else:
                self.stats["downloaded"] = 1
                completed_files["bad.pdf"] = b"recovered"
            return destination

    first = SyncManager(downloader_factory=RetryDownloader).sync_course(course, requests.Session())
    second = SyncManager(downloader_factory=RetryDownloader).sync_course(course, requests.Session())

    assert first.status == "partial"
    assert second.status == "success"
    assert second.skipped == 1
    assert second.downloaded == 1
    assert second.errors == 0
