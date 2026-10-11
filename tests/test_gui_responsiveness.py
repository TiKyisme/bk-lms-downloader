import queue
from types import SimpleNamespace

import bklms_downloader.gui as gui
from bklms_downloader.course_store import CourseStore
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


def test_main_course_rows_start_unchecked_and_rebuild_keeps_session_selection(
    monkeypatch,
    tmp_path,
):
    class FakeWidget:
        def __init__(self, *_args, variable=None, **_kwargs):
            self.variable = variable

        def grid(self, *_args, **_kwargs):
            pass

        def bind(self, *_args, **_kwargs):
            pass

        def configure(self, **_kwargs):
            pass

    frame = gui.CourseRow.__mro__[1]
    for method in (
        "__init__",
        "grid_columnconfigure",
        "grid_propagate",
        "grid",
        "bind",
        "configure",
        "destroy",
    ):
        monkeypatch.setattr(frame, method, lambda *args, **kwargs: None)
    monkeypatch.setattr(gui.tk, "BooleanVar", FakeVar)
    monkeypatch.setattr(gui.ctk, "CTkCheckBox", FakeWidget)
    monkeypatch.setattr(gui.ctk, "CTkLabel", FakeWidget)

    store = CourseStore(tmp_path / "courses.json")
    first = store.add("https://lms.hcmut.edu.vn/course/view.php?id=101", tmp_path / "one")
    second = store.add("https://lms.hcmut.edu.vn/course/view.php?id=102", tmp_path / "two")
    app = App.__new__(App)
    app.syncing = False
    app.store = store
    app.course_rows = {}
    app.course_scroll = object()
    app.current_course_id = None
    app.course_detail_var = FakeVar("")
    app._show_course_detail = lambda _course_id: None

    App._refresh_courses(app)

    assert {course_id: row.check_var.get() for course_id, row in app.course_rows.items()} == {
        first.id: False,
        second.id: False,
    }

    first_row = app.course_rows[first.id]
    first_row.check_var.set(True)
    first_row._toggle()
    assert store.get(first.id).selected is True

    App._refresh_courses(app)

    assert app.course_rows[first.id].check_var.get() is True
    assert app.course_rows[second.id].check_var.get() is False


def test_sync_all_and_ai_all_include_courses_even_when_all_checkboxes_are_unchecked(monkeypatch):
    courses = [
        Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "one"),
        Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", "two"),
    ]
    assert all(course.selected is False for course in courses)

    app = App.__new__(App)
    app.login_opening = False
    app.syncing = False
    app.driver = object()
    app.store = SimpleNamespace(list=lambda: courses)
    app.sync_elapsed_var = FakeVar("")
    app.overall_var = FakeVar("")
    app.current_course_var = FakeVar("")
    app._set_busy = lambda _busy: None
    app._reset_progress_state = lambda: None
    app._set_summary_message = lambda _message: None
    app._set_login_status = lambda *_args: None
    app._log = lambda _message: None

    started = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            started.append((target, daemon))

        def start(self):
            pass

    monkeypatch.setattr(gui.threading, "Thread", FakeThread)
    App._start_sync(app, selected_only=False)

    assert app.progress_total == 2
    assert len(started) == 1
    assert started[0][1] is True

    ai_app = App.__new__(App)
    ai_app.syncing = False
    ai_app.store = SimpleNamespace(list=lambda: courses)
    confirmed = []
    ai_app._confirm_ai_batch = confirmed.append
    App._prepare_all_courses_for_ai(ai_app)

    assert confirmed == [courses]


def test_delete_all_ignores_unchecked_state(monkeypatch):
    courses = [
        Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "one"),
        Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", "two"),
    ]
    confirmations = []

    class FakeConfirmation:
        def __init__(self, _parent, **kwargs):
            confirmations.append(kwargs)

    monkeypatch.setattr(gui, "DeleteConfirmationDialog", FakeConfirmation)
    app = App.__new__(App)
    app.syncing = False
    app.store = SimpleNamespace(list=lambda: courses)
    app._clear_courses_from_app = lambda: None

    App._delete_all_courses(app)

    assert len(confirmations) == 1
    assert "2 course" in confirmations[0]["message"]


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


def test_event_drain_continues_after_one_handler_exception():
    app = App.__new__(App)
    app.events = queue.Queue()
    app.events.put({"event": "bad"})
    app.events.put({"event": "good"})
    handled = []
    scheduled = []

    def handle(event):
        if event["event"] == "bad":
            raise ValueError("malformed event")
        handled.append(event["event"])

    app._handle_event = handle
    app.after_idle = lambda callback: scheduled.append(("idle", callback))
    app.after = lambda delay, callback: scheduled.append((delay, callback))

    App._drain_events(app)

    assert handled == ["good"]
    assert app.events.empty()
    assert scheduled == [(120, app._drain_events)]


def test_event_drain_does_not_schedule_tk_after_root_destroyed():
    app = App.__new__(App)
    app._destroyed = True
    app.events = queue.Queue()
    app.events.put({"event": "stale"})
    app.after = lambda *_args: pytest.fail("must not call after on destroyed root")
    app.after_idle = app.after

    App._drain_events(app)

    assert app.events.qsize() == 1


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
