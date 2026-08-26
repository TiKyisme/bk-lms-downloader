import requests

from bklms_downloader.utils import (
    activity_type,
    extract_course_code,
    filename_from_response,
    is_course_url,
    is_video_url,
    repair_mojibake,
    safe_name,
)


def test_course_url():
    assert is_course_url("https://lms.hcmut.edu.vn/course/view.php?id=123456")
    assert not is_course_url("https://example.com/course/view.php?id=1")


def test_extract_course_code_is_conservative():
    assert extract_course_code("Mạng máy tính (TN) (CO3094)_NGUYỄN") == "CO3094"
    assert extract_course_code("Mạng máy tính (CO3093)_Lớp") == "CO3093"
    assert extract_course_code("Principles of Programming Languages") is None


def test_activity_type():
    assert activity_type("https://lms.hcmut.edu.vn/mod/resource/view.php?id=1") == "resource"
    assert activity_type("https://lms.hcmut.edu.vn/mod/page/view.php?id=2") == "page"
    assert activity_type("https://lms.hcmut.edu.vn/course/view.php?id=3") == "course"


def test_safe_name_windows_chars_and_brackets():
    value = safe_name('Chapter: 1 / Intro [L02,L03]?')
    assert ":" not in value
    assert "/" not in value
    assert "?" not in value
    assert "[L02,L03]" in value


def test_video_detection_is_internal_only():
    assert is_video_url("https://lms.hcmut.edu.vn/pluginfile.php/1/x/video.mp4")
    assert not is_video_url("https://lms.hcmut.edu.vn/pluginfile.php/1/x/slides.pdf")


def test_repair_common_vietnamese_mojibake():
    broken = "01_CHÆ¯Æ\xa0NG 1_Giá»\x9bi THIá»\x86U KHOA Há»\x8cC TRÃ\x81I Ä\x90áº¤T.pdf"
    assert repair_mojibake(broken) == "01_CHƯƠNG 1_Giới THIỆU KHOA HỌC TRÁI ĐẤT.pdf"
    assert safe_name(broken, 180) == "01_CHƯƠNG 1_Giới THIỆU KHOA HỌC TRÁI ĐẤT.pdf"


def test_content_disposition_legacy_utf8_filename_is_repaired():
    response = requests.Response()
    response.url = "https://lms.hcmut.edu.vn/pluginfile.php/1/course/file.pdf"
    response.headers["Content-Disposition"] = (
        'attachment; filename="Slide ChÆ°Æ¡ng 1 - Giá»\x9bi Thiá»\x87u.pdf"'
    )
    # Use a realistic Latin-1 header sequence that round-trips to UTF-8.
    original = "Slide Chương 1 - Giới Thiệu.pdf"
    response.headers["Content-Disposition"] = (
        'attachment; filename="' + original.encode("utf-8").decode("latin-1") + '"'
    )
    assert filename_from_response(response, "fallback") == original


def test_content_disposition_rfc5987_utf8_filename():
    response = requests.Response()
    response.url = "https://lms.hcmut.edu.vn/pluginfile.php/1/course/file.pdf"
    response.headers["Content-Disposition"] = (
        "attachment; filename*=UTF-8''Slide%20Ch%C6%B0%C6%A1ng%201%20-%20Gi%E1%BB%9Bi%20Thi%E1%BB%87u.pdf"
    )
    assert filename_from_response(response, "fallback") == "Slide Chương 1 - Giới Thiệu.pdf"
