from urllib.parse import parse_qs, urlparse

from bklms_downloader.feedback import FEEDBACK_TEMPLATE, GITHUB_ISSUES_NEW_URL, FeedbackDraft


def make_draft(**changes) -> FeedbackDraft:
    values = {
        "feedback_type": "Báo lỗi",
        "title": "Không thể đồng bộ môn học",
        "description": "Ứng dụng dừng sau khi chọn môn học.",
        "app_version": "1.2.0",
        "platform": "Windows 11",
    }
    values.update(changes)
    return FeedbackDraft(**values)


def test_feedback_validation_rejects_missing_or_invalid_fields():
    assert make_draft(title=" ").validate() is not None
    assert make_draft(description="ngắn").validate() is not None
    assert make_draft(feedback_type="Không hợp lệ").validate() is not None
    assert make_draft().validate() is None


def test_feedback_issue_url_percent_encodes_vietnamese_and_contains_only_safe_metadata():
    draft = make_draft(
        feedback_type="Đề xuất tính năng",
        title="Hỗ trợ thư mục học kỳ",
        description="Mô tả tiếng Việt có dấu để người dùng xem lại.",
        platform="macOS 15",
    )

    parsed = urlparse(draft.github_issue_url())
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GITHUB_ISSUES_NEW_URL
    assert query["template"] == [FEEDBACK_TEMPLATE]
    assert query["title"] == ["Hỗ trợ thư mục học kỳ"]
    body = query["body"][0]
    assert "Đề xuất tính năng" in body
    assert "Phiên bản: 1.2.0" in body
    assert "Hệ điều hành: macOS 15" in body
    assert "C:\\Users\\" not in body
    assert "MoodleSession=" not in body
    assert "Authorization: Bearer" not in body
