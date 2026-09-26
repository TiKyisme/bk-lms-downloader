from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bklms_downloader.ai_prepare import AICoursePreparationResult, AIBatchPreparer
from bklms_downloader.gui import App
from bklms_downloader.models import Course, CourseSyncResult
from bklms_downloader.sync_progress import (
    ACTIVE_COURSE_MAX,
    cap_active_course_fraction,
    course_activity_fraction,
)


class FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def progress_app() -> App:
    app = App.__new__(App)
    app._destroyed = True
    app.progress = SimpleNamespace(set=lambda value: setattr(app, "bar_value", value))
    app.overall_var = FakeVar()
    app.displayed_progress = 0.0
    app.target_progress = 0.0
    app._progress_animation_scheduled = False
    app._progress_total_courses = 2
    app._progress_completed_courses = 0
    app._progress_current_course_index = 0
    app._progress_current_course_fraction = 0.0
    app._sync_total_courses = 2
    app._sync_completed_courses = 0
    app._sync_course_index = 0
    app._sync_current_course_fraction = 0.0
    return app


def test_two_course_sync_completion_never_double_counts_active_course():
    app = progress_app()
    app.current_course_var = FakeVar()
    app.course_rows = {}
    app._refresh_course_row = lambda _course_id: None
    app._log = lambda *_args: None
    first = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "one", name="One")
    second = Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", "two", name="Two")

    App._handle_event(app, {"event": "course_sync_start", "course": first, "index": 1, "total": 2})
    App._handle_crawler_event(
        app,
        {"event": "activity_complete", "activity_index": 10, "activity_total": 10},
    )
    assert app.target_progress < 0.5

    App._handle_event(
        app,
        {
            "event": "course_sync_complete",
            "course": first,
            "result": CourseSyncResult("1", first.url, first.name, None, status="success"),
            "index": 1,
            "total": 2,
        },
    )
    assert app.target_progress == 0.5

    App._handle_event(app, {"event": "course_sync_start", "course": second, "index": 2, "total": 2})
    App._handle_crawler_event(
        app,
        {"event": "activity_complete", "activity_index": 10, "activity_total": 10},
    )
    assert 0.5 < app.target_progress < 1.0

    App._handle_event(
        app,
        {
            "event": "course_sync_complete",
            "course": second,
            "result": CourseSyncResult("2", second.url, second.name, None, status="success"),
            "index": 2,
            "total": 2,
        },
    )
    assert app.target_progress == 1.0


def test_active_last_activity_is_capped_below_course_boundary():
    raw_fraction = course_activity_fraction(10, 10, completed=True)

    assert raw_fraction == 1.0
    assert cap_active_course_fraction(raw_fraction) == ACTIVE_COURSE_MAX


def test_ai_two_course_events_count_completed_courses_not_current_index():
    app = progress_app()
    app.current_course_var = FakeVar()
    app._log = lambda *_args: None
    app._format_pack_size = lambda _path: ""

    first = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "one", name="One", code="CO1")
    second = Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", "two", name="Two", code="CO2")

    App._handle_event(app, {"event": "ai_prepare_course_start", "course": first, "index": 1, "total": 2})
    assert "course 1/2" in app.current_course_var.get()
    assert app._progress_completed_courses == 0

    App._handle_event(
        app,
        {
            "event": "ai_prepare_progress",
            "course": first,
            "phase": "source_processing",
            "message": "Đang xử lý tài liệu 8/19...",
            "course_fraction": 0.8,
        },
    )
    assert 0.0 < app.target_progress < 0.5

    App._handle_event(
        app,
        {
            "event": "ai_prepare_course_complete",
            "course": first,
            "result": AICoursePreparationResult(first, output=Path("one.zip")),
            "index": 1,
            "total": 2,
        },
    )
    assert app._progress_completed_courses == 1
    assert app.target_progress == 0.5

    App._handle_event(app, {"event": "ai_prepare_course_start", "course": second, "index": 2, "total": 2})
    assert "course 2/2" in app.current_course_var.get()
    assert "1 / 2 course hoàn tất" in app.overall_var.get()

    App._handle_event(
        app,
        {
            "event": "ai_prepare_progress",
            "course": second,
            "phase": "finalization",
            "message": "Đang đóng gói và kiểm tra ZIP...",
            "course_fraction": 0.8,
        },
    )
    assert 0.5 < app.target_progress < 1.0

    App._handle_event(
        app,
        {
            "event": "ai_prepare_course_complete",
            "course": second,
            "result": AICoursePreparationResult(second, output=Path("two.zip")),
            "index": 2,
            "total": 2,
        },
    )
    assert app._progress_completed_courses == 2
    assert app.target_progress == 1.0


def test_progress_text_uses_displayed_bar_position_not_distant_target():
    app = progress_app()
    app._destroyed = False
    callbacks = []
    app._schedule_ui_callback = lambda delay, callback: callbacks.append((delay, callback)) or True

    App._set_batch_progress_target(app, ACTIVE_COURSE_MAX, completed_courses=1)
    assert app.overall_var.get().startswith("0%")

    App._animate_progress(app)
    assert app.overall_var.get().startswith("4%")


def test_batch_preparer_forwards_structured_ai_progress_events(tmp_path: Path):
    first = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", str(tmp_path / "one"), name="One")
    events = []

    class ProgressPreparer:
        def prepare(self, course_root, *, progress_callback=None, **_kwargs):
            progress_callback({
                "phase": "source_processing",
                "course_fraction": 0.5,
                "completed": 1,
                "total": 2,
                "message": "Đang xử lý tài liệu 1/2...",
            })
            return Path(course_root).parent / "one.zip"

    result = AIBatchPreparer(lambda: ProgressPreparer()).prepare_courses(
        [first],
        lambda course: Path(course.output),
        events.append,
    )

    assert result.succeeded
    progress = [event for event in events if event["event"] == "ai_prepare_progress"]
    assert progress and progress[0]["course_fraction"] == 0.5
    assert progress[0]["course"].id == first.id
