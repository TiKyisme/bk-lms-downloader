import queue

from bklms_downloader.gui import (
    LIVE_LOG_MAX_LINES,
    LIVE_LOG_TRIM_TO_LINES,
    MAX_UI_EVENTS_PER_TICK,
    App,
)
from bklms_downloader.models import Course


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeRow:
    def __init__(self):
        self.check_var = FakeVar(False)
        self.updated = []
        self.current = []

    def update_course(self, course):
        self.updated.append(course)

    def set_current(self, current):
        self.current.append(current)


def test_checkbox_toggle_updates_one_row_without_rebuilding_course_list():
    course = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "out")

    class Store:
        def get(self, _course_id):
            return course

        def edit(self, _course_id, **changes):
            course.selected = bool(changes["selected"])
            return course

    app = App.__new__(App)
    app.syncing = False
    app.store = Store()
    row = FakeRow()
    app.course_rows = {course.id: row}
    app.current_course_id = None
    app._show_course_detail = lambda _course_id: None
    app._refresh_courses = lambda: (_ for _ in ()).throw(AssertionError("full rebuild"))

    App._toggle_course(app, course.id, False)

    assert course.selected is False
    assert row.updated == [course]
    assert app.current_course_id == course.id


def test_event_drain_uses_a_bounded_per_tick_budget():
    app = App.__new__(App)
    app.events = queue.Queue()
    for index in range(MAX_UI_EVENTS_PER_TICK + 5):
        app.events.put({"event": "test", "index": index})
    handled = []
    scheduled = []
    app._handle_event = handled.append
    app.after_idle = lambda callback: scheduled.append(("idle", callback))
    app.after = lambda delay, callback: scheduled.append((delay, callback))

    App._drain_events(app)

    assert len(handled) == MAX_UI_EVENTS_PER_TICK
    assert app.events.qsize() == 5
    assert scheduled[0][0] == "idle"


def test_download_heartbeat_updates_headline_without_flooding_live_log():
    app = App.__new__(App)
    app.current_course_var = FakeVar()
    logged = []
    app._log = logged.append

    App._handle_crawler_event(
        app,
        {"event": "download_progress", "message": "Đang tải: lecture.pdf"},
    )
    App._handle_crawler_event(
        app,
        {"event": "file_downloaded", "message": "Đã tải: lecture.pdf"},
    )

    assert app.current_course_var.get() == "Đang tải: lecture.pdf"
    assert logged == ["[OK] Đã tải: lecture.pdf"]


class FakeText:
    def __init__(self):
        self.deleted = []

    def configure(self, **_kwargs):
        pass

    def insert(self, *_args):
        pass

    def delete(self, start, end):
        self.deleted.append((start, end))

    def see(self, _where):
        pass


def test_live_activity_log_is_trimmed_in_batches():
    app = App.__new__(App)
    app.log_text = FakeText()
    app._live_log_line_count = LIVE_LOG_MAX_LINES

    App._log(app, "new line")

    assert app._live_log_line_count == LIVE_LOG_TRIM_TO_LINES
    assert app.log_text.deleted == [
        ("1.0", f"{LIVE_LOG_MAX_LINES - LIVE_LOG_TRIM_TO_LINES + 2}.0")
    ]
