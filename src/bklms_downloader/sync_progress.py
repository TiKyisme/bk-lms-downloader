"""Pure helpers for the granular sync progress model."""

from __future__ import annotations


def clamp_progress(value: float | int | None) -> float:
    """Return a finite progress value in the inclusive ``0..1`` range."""
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if numeric != numeric:  # NaN
        return 0.0
    return max(0.0, min(1.0, numeric))


def course_activity_fraction(
    activity_index: int | None,
    activity_total: int | None,
    *,
    bytes_written: int | None = None,
    bytes_total: int | None = None,
    completed: bool = False,
) -> float:
    """Calculate a monotonic-friendly fraction within one course.

    An activity starts at ``(N - 1) / total``.  A known-size download may fill
    the current activity fraction using its byte count.  Completion advances
    to ``N / total``.  With no activities, the caller can complete the course
    from the course-level event without dividing by zero.
    """
    try:
        total = max(0, int(activity_total or 0))
    except (TypeError, ValueError):
        total = 0
    if total == 0:
        return 0.0

    try:
        index = int(activity_index or 1)
    except (TypeError, ValueError):
        index = 1
    index = max(1, min(total, index))
    completed_fraction = index / total
    if completed:
        return completed_fraction

    fraction = (index - 1) / total
    if bytes_total is not None and bytes_written is not None:
        try:
            total_bytes = int(bytes_total)
            written_bytes = max(0, int(bytes_written))
        except (TypeError, ValueError):
            total_bytes = 0
            written_bytes = 0
        if total_bytes > 0:
            fraction = (index - 1 + clamp_progress(written_bytes / total_bytes)) / total
    return max(0.0, min(completed_fraction, fraction))


def overall_progress(
    completed_courses: int,
    total_courses: int,
    current_course_fraction: float = 0.0,
) -> float:
    """Combine completed courses and the active course into one fraction."""
    try:
        total = max(0, int(total_courses))
        completed = max(0, min(total, int(completed_courses)))
    except (TypeError, ValueError):
        return 0.0
    if total == 0:
        return 0.0
    return clamp_progress((completed + clamp_progress(current_course_fraction)) / total)


def advance_displayed_progress(
    displayed_progress: float,
    target_progress: float,
    step: float = 0.04,
) -> float:
    """Move toward a target without overshooting or regressing."""
    displayed = clamp_progress(displayed_progress)
    target = clamp_progress(target_progress)
    if target <= displayed:
        return displayed
    try:
        increment = max(0.0, float(step))
    except (TypeError, ValueError):
        increment = 0.0
    return min(target, displayed + increment)


def format_overall_progress(
    progress: float,
    completed_courses: int,
    total_courses: int,
) -> str:
    """Format the student-facing overall sync label."""
    try:
        completed = max(0, int(completed_courses))
        total = max(0, int(total_courses))
    except (TypeError, ValueError):
        completed, total = 0, 0
    completed = min(completed, total)
    percent = int(round(clamp_progress(progress) * 100))
    return f"{percent}% • {completed} / {total} course hoàn tất"
