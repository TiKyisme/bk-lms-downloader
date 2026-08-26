from pathlib import Path

import requests

from bklms_downloader.course_store import CourseStore
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
        return self.output / outcome.get("folder", "Course")


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
