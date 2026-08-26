from bklms_downloader.gui import App
from bklms_downloader.models import Course
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
