from pathlib import Path

import pytest
import requests

from bklms_downloader.course_discovery import (
    CourseDiscoveryError,
    SessionExpiredError,
    discover_courses,
    parse_discovered_courses,
)


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, url, text="", status_code=200):
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("bad response")


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)

    def get(self, *_args, **_kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_parse_standard_dashboard_cards_with_unicode_and_codes():
    courses = parse_discovered_courses((FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8"))

    assert [(course.course_id, course.code) for course in courses] == [("2013", "CO2013"), ("1013", "GE1013")]
    assert courses[0].name == "Hệ cơ sở dữ liệu (CO2013)"


def test_parse_alternate_markup_and_deduplicate_urls():
    html = (FIXTURES / "dashboard_alternate.html").read_text(encoding="utf-8")
    html += '<a href="/course/view.php?id=3094">duplicate</a>'

    courses = parse_discovered_courses(html)

    assert [course.course_id for course in courses] == ["3001", "3094"]
    assert courses[1].name.startswith("Mạng máy tính")


def test_empty_and_malformed_dashboard_are_safe():
    assert parse_discovered_courses("<main>Nothing here</main>") == []
    assert parse_discovered_courses("<a href='broken'>") == []


def test_discovery_combines_sources_and_detects_expired_session():
    standard = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    alternate = (FIXTURES / "dashboard_alternate.html").read_text(encoding="utf-8")
    session = FakeSession(
        [
            FakeResponse("https://lms.hcmut.edu.vn/my/", standard),
            FakeResponse("https://lms.hcmut.edu.vn/course/index.php", alternate),
        ]
    )
    assert len(discover_courses(session)) == 4

    expired = FakeSession([FakeResponse("https://lms.hcmut.edu.vn/login/index.php")])
    with pytest.raises(SessionExpiredError, match="đăng nhập"):
        discover_courses(expired)


def test_discovery_failure_is_human_friendly():
    session = FakeSession([requests.Timeout(), requests.ConnectionError()])
    with pytest.raises(CourseDiscoveryError, match="thêm course bằng URL"):
        discover_courses(session)
