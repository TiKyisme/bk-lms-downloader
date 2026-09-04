"""Synthetic GUI smoke coverage for exclusive nested wheel routing."""

from __future__ import annotations

import traceback
from pathlib import Path

from . import gui
from .models import Course


class _SmokeStore:
    def __init__(self, *_args, **_kwargs) -> None:
        self._courses = [
            Course(
                id=f"smoke-{index}",
                url=f"https://lms.hcmut.edu.vn/course/view.php?id={1000 + index}",
                output=".",
                name=f"Synthetic Course {index:02d}",
                code=f"SM{index:02d}",
            )
            for index in range(40)
        ]

    def list(self) -> list[Course]:
        return list(self._courses)

    def get(self, course_id: str) -> Course | None:
        return next((course for course in self._courses if course.id == course_id), None)


def _view_start(widget) -> float:
    return float(widget.yview()[0])


def _assert_same(before: float, after: float, label: str) -> None:
    assert abs(before - after) < 1e-6, f"{label} unexpectedly moved: {before} -> {after}"


def _wheel(app: gui.App, widget, delta: int) -> None:
    widget.event_generate("<MouseWheel>", delta=delta)
    app.update_idletasks()
    app.update()


def run_scroll_runtime_smoke() -> None:
    """Exercise main/course/activity/modal wheel routing without user data."""
    original_store = gui.CourseStore
    original_update_check = gui.App._check_for_updates
    gui.CourseStore = _SmokeStore
    gui.App._check_for_updates = lambda _self: None
    app: gui.App | None = None
    try:
        app = gui.App()
        app.geometry("1000x700")
        # Guarantee that the outer CTkScrollableFrame itself has overflow.
        filler = gui.ctk.CTkFrame(app.main_scroll, height=700, fg_color="transparent")
        filler.grid(row=4, column=0, sticky="ew")
        filler.grid_propagate(False)
        for index in range(80):
            app._log(f"[SCROLL SMOKE] activity {index:02d}")
        app.update_idletasks()
        app.update()

        # Long/short activity headlines may wrap inside the progress pane, but
        # must never alter the allocated Recent Activity viewport.
        log_size = (app.log_area.winfo_width(), app.log_area.winfo_height())
        app.current_course_var.set(
            "Đang tải: " + ("CHƯƠNG 03 TÀI LIỆU RẤT DÀI " * 12) + "(Phần 4)"
        )
        app.update_idletasks()
        app.update()
        assert (app.log_area.winfo_width(), app.log_area.winfo_height()) == log_size
        app.current_course_var.set("Đang tải: lecture.pdf")
        app.update_idletasks()
        app.update()
        assert (app.log_area.winfo_width(), app.log_area.winfo_height()) == log_size

        main_canvas = app.main_scroll._parent_canvas
        course_canvas = app.course_scroll._parent_canvas
        activity_text = app.log_text._textbox
        assert course_canvas.yview() != (0.0, 1.0)
        assert activity_text.yview() != (0.0, 1.0)
        assert main_canvas.yview() != (0.0, 1.0)

        course_label = next(iter(app.course_rows.values())).name_label
        course_canvas.yview_moveto(0)
        main_canvas.yview_moveto(0)
        main_before = _view_start(main_canvas)
        _wheel(app, course_label, -120)
        assert _view_start(course_canvas) > 0
        _assert_same(main_before, _view_start(main_canvas), "main page over course list")

        # Child ownership does not change at top/bottom boundaries.
        main_canvas.yview_moveto(0.5)
        main_before = _view_start(main_canvas)
        course_canvas.yview_moveto(0)
        _wheel(app, course_label, 120)
        _assert_same(main_before, _view_start(main_canvas), "main page at course top")
        course_canvas.yview_moveto(1)
        _wheel(app, course_label, -120)
        _assert_same(main_before, _view_start(main_canvas), "main page at course bottom")

        activity_text.yview_moveto(0)
        main_before = _view_start(main_canvas)
        _wheel(app, activity_text, -120)
        assert _view_start(activity_text) > 0
        _assert_same(main_before, _view_start(main_canvas), "main page over activity log")
        activity_text.yview_moveto(0)
        _wheel(app, activity_text, 120)
        _assert_same(main_before, _view_start(main_canvas), "main page at activity top")
        activity_text.yview_moveto(1)
        _wheel(app, activity_text, -120)
        _assert_same(main_before, _view_start(main_canvas), "main page at activity bottom")

        main_canvas.yview_moveto(0)
        _wheel(app, filler, -120)
        assert _view_start(main_canvas) > 0

        modal_courses = [
            Course(
                id=f"modal-{index}",
                url=f"https://lms.hcmut.edu.vn/course/view.php?id={2000 + index}",
                output=".",
                name=f"Modal Course {index:02d}",
                code=f"MD{index:02d}",
            )
            for index in range(40)
        ]
        modal = gui.ImportCoursesDialog(app, modal_courses, lambda _courses, _output: None)
        app.update_idletasks()
        app.update()
        modal_scroll = app._scroll_regions[modal._scroll_owner]
        modal_canvas = modal_scroll._parent_canvas
        assert modal_canvas.yview() != (0.0, 1.0)
        main_canvas.yview_moveto(0.5)
        main_before = _view_start(main_canvas)
        modal_canvas.yview_moveto(0)
        _wheel(app, modal_canvas, -120)
        assert _view_start(modal_canvas) > 0
        _assert_same(main_before, _view_start(main_canvas), "main page behind modal")
        modal.destroy()
        assert modal._scroll_owner not in app._scroll_regions
    finally:
        if app is not None:
            app.destroy()
        gui.CourseStore = original_store
        gui.App._check_for_updates = original_update_check


def run_scroll_runtime_self_test() -> int:
    error_log = Path("scroll-self-test-error.log")
    try:
        run_scroll_runtime_smoke()
    except Exception:
        error_log.write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    error_log.unlink(missing_ok=True)
    try:
        print("Synthetic nested scroll routing: courses, activity, main, modal: OK")
    except (AttributeError, OSError, UnicodeError):
        pass
    return 0
