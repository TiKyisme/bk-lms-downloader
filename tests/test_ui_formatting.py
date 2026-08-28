from bklms_downloader.gui import App, shorten_sync_activity
from bklms_downloader.models import Course, checked_courses
from bklms_downloader.ui_theme import THEME


def test_course_status_text_uses_the_modern_status_palette():
    assert App._status_text(Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "out")) == (
        "Chưa đồng bộ",
        THEME.muted_text,
    )
    assert App._status_text(
        Course("2", "https://lms.hcmut.edu.vn/course/view.php?id=2", "out", last_status="success", last_downloaded=3)
    ) == ("3 file mới", THEME.success)
    assert App._status_text(
        Course("3", "https://lms.hcmut.edu.vn/course/view.php?id=3", "out", last_status="up_to_date")
    ) == ("Giữ nguyên", THEME.primary)


def test_course_status_error_and_last_sync_formatting_are_human_friendly():
    course = Course(
        "4",
        "https://lms.hcmut.edu.vn/course/view.php?id=4",
        "out",
        last_status="error",
        last_errors=2,
    )

    assert App._status_text(course) == ("2 lỗi", THEME.danger)
    assert App._format_last_sync(None) == "Chưa đồng bộ"
    assert App._format_last_sync("2026-08-26T13:20:00+07:00") == "26/08 13:20"


def test_checked_courses_is_shared_source_of_truth_for_batch_actions():
    checked = Course("1", "https://lms.hcmut.edu.vn/course/view.php?id=1", "out")
    unchecked = Course(
        "2",
        "https://lms.hcmut.edu.vn/course/view.php?id=2",
        "out",
        selected=False,
    )

    assert checked_courses([checked, unchecked]) == [checked]
    assert checked_courses([unchecked]) == []


def test_long_sync_activity_headline_is_compact_but_keeps_meaningful_ends():
    message = "Đang tải: " + ("CHƯƠNG 03 TÀI LIỆU DÀI " * 8) + "(Phần 4)"

    compact = shorten_sync_activity(message, limit=64)

    assert compact.startswith("Đang tải:")
    assert compact.endswith("(Phần 4)")
    assert "…" in compact
    assert len(compact) <= 64
    assert shorten_sync_activity("Đang tải: lecture.pdf", limit=64) == "Đang tải: lecture.pdf"
