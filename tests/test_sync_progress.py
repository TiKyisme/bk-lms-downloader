from __future__ import annotations

from types import SimpleNamespace

from bklms_downloader.gui import App
from bklms_downloader.models import SyncBatchResult
from bklms_downloader.sync_progress import (
    advance_displayed_progress,
    course_activity_fraction,
    format_overall_progress,
    overall_progress,
)


def test_one_course_activity_progress_reaches_one_only_after_completion():
    assert overall_progress(0, 1, course_activity_fraction(1, 5)) == 0.0
    assert overall_progress(0, 1, course_activity_fraction(3, 5, completed=True)) == 0.6
    assert overall_progress(0, 1, course_activity_fraction(5, 5, completed=True)) == 1.0


def test_three_course_label_counts_only_completed_courses():
    progress = overall_progress(2, 3, 0.0)

    assert progress == 2 / 3
    assert format_overall_progress(progress, 2, 3) == "67% • 2 / 3 course hoàn tất"


def test_activity_fraction_supports_five_of_ten_and_unknown_totals():
    assert course_activity_fraction(5, 10) == 0.4
    assert course_activity_fraction(5, 10, completed=True) == 0.5
    assert course_activity_fraction(1, 0) == 0.0
    assert course_activity_fraction(1, None) == 0.0


def test_known_and_unknown_content_lengths_have_safe_fallbacks():
    assert course_activity_fraction(2, 4, bytes_written=50, bytes_total=100) == 0.375
    assert course_activity_fraction(2, 4, bytes_written=50, bytes_total=None) == 0.25
    assert course_activity_fraction(2, 4, bytes_written=500, bytes_total=100) == 0.5


def test_progress_animation_approaches_target_without_overshoot_or_regress():
    values = [0.0]
    while values[-1] < 1.0:
        values.append(advance_displayed_progress(values[-1], 1.0))

    assert values == sorted(values)
    assert values[-1] == 1.0
    assert all(value <= 1.0 for value in values)
    assert advance_displayed_progress(0.8, 0.4) == 0.8


def test_gui_animation_schedules_at_ui_rate_and_stops_after_destroy():
    callbacks: list[tuple[int, object]] = []

    class FakeProgress:
        def __init__(self):
            self.values: list[float] = []

        def set(self, value):
            self.values.append(value)

    app = App.__new__(App)
    app._destroyed = False
    app.displayed_progress = 0.0
    app.target_progress = 1.0
    app._progress_animation_scheduled = False
    app.progress = FakeProgress()
    app._schedule_ui_callback = lambda delay, callback: callbacks.append((delay, callback)) or True

    app._animate_progress()
    assert callbacks[0][0] == 40
    while callbacks:
        _delay, callback = callbacks.pop(0)
        callback()

    assert app.displayed_progress == 1.0
    assert app.progress.values[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in app.progress.values)

    app._destroyed = True
    previous_values = list(app.progress.values)
    app._animate_progress()
    assert app.progress.values == previous_values


def test_cancelled_batch_does_not_force_progress_to_one():
    recorded: dict[str, object] = {}
    app = App.__new__(App)
    app.syncing = True
    app.sync_cancel_event = SimpleNamespace()
    app.sync_started_at = 1.0
    app.sync_elapsed_var = SimpleNamespace(set=lambda _value: None)
    app.progress = SimpleNamespace(set=lambda value: recorded.__setitem__("progress", value))
    app.overall_var = SimpleNamespace(set=lambda value: recorded.__setitem__("overall", value))
    app.current_course_var = SimpleNamespace(set=lambda _value: None)
    app.cancel_sync_btn = SimpleNamespace(configure=lambda **_kwargs: None)
    app._destroyed = True
    app._close_requested = True
    app.displayed_progress = 0.0
    app.target_progress = 0.0
    app._progress_animation_scheduled = False
    app._refresh_courses = lambda: None
    app._set_login_status = lambda *_args: None
    app._set_summary_message = lambda _message: None
    app._set_summary_counts = lambda *_args: None
    app._set_busy = lambda busy: setattr(app, "syncing", busy)

    batch = SyncBatchResult([], cancelled=True)
    App._complete_sync(app, batch, total=3)

    assert app.__dict__["target_progress"] == 0.0
    assert recorded["overall"] == "0% • 0 / 3 course hoàn tất"
