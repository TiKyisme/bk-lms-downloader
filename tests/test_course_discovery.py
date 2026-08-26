from pathlib import Path

import pytest
import requests

from bklms_downloader.course_discovery import (
    CourseDiscoveryError,
    SessionExpiredError,
    discover_courses,
    discover_courses_from_browser,
    discover_courses_with_browser_fallback,
    parse_discovered_courses,
)


FIXTURES = Path(__file__).parent / "fixtures"
MY_COURSES_URL = "https://lms.hcmut.edu.vn/my/courses.php"


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
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSwitchTo:
    def __init__(self, driver):
        self.driver = driver

    def new_window(self, _kind):
        self.driver.window_handles.append("temporary")
        self.driver.current_window_handle = "temporary"

    def window(self, handle):
        self.driver.current_window_handle = handle
        self.driver.switched_to.append(handle)


class FakeAnchor:
    def __init__(self, href, text):
        self.href = href
        self.text = text

    def get_attribute(self, name):
        if name == "href":
            return self.href
        if name == "textContent":
            return self.text
        return ""


class FakeDriver:
    def __init__(self, rendered_html="", *, fail_get=False, anchors=None):
        self.window_handles = ["original"]
        self.current_window_handle = "original"
        self.switch_to = FakeSwitchTo(self)
        self.rendered_html = rendered_html
        self.fail_get = fail_get
        self.anchors = anchors or []
        self.closed = []
        self.get_calls = []
        self.switched_to = []
        self.page_by_handle = {"original": "https://lms.hcmut.edu.vn/my/"}

    @property
    def page_source(self):
        return self.rendered_html

    def get(self, url):
        self.get_calls.append(url)
        if self.fail_get:
            raise RuntimeError("rendered discovery failed")
        self.page_by_handle[self.current_window_handle] = url

    def execute_script(self, script):
        if script == "return document.readyState":
            return "complete"
        raise AssertionError(f"Unexpected script: {script}")

    def find_elements(self, _by, selector):
        if selector == "a[href*='/course/view.php?id=']":
            return self.anchors
        return []

    def close(self):
        self.closed.append(self.current_window_handle)
        self.window_handles.remove(self.current_window_handle)


def test_parse_standard_course_cards_with_unicode_and_codes():
    courses = parse_discovered_courses((FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8"))

    assert [(course.course_id, course.code) for course in courses] == [("2013", "CO2013"), ("1013", "GE1013")]
    assert courses[0].name == "Hệ cơ sở dữ liệu (CO2013)"


def test_parse_alternate_markup_and_deduplicate_urls():
    html = (FIXTURES / "dashboard_alternate.html").read_text(encoding="utf-8")
    html += '<div class="course-card"><a href="/course/view.php?id=3094">duplicate</a></div>'

    courses = parse_discovered_courses(html)

    assert [course.course_id for course in courses] == ["3001", "3094"]
    assert courses[1].name.startswith("Mạng máy tính")


def test_parse_ignores_unrelated_navigation_course_links():
    html = """
    <nav><a href="/course/view.php?id=9999">Điều hướng không phải môn học</a></nav>
    <div class="course-card"><h3 class="coursename">
      <a href="/course/view.php?id=3093">Hệ điều hành (CO3093)</a>
    </h3></div>
    """

    courses = parse_discovered_courses(html)

    assert [(course.course_id, course.name, course.code) for course in courses] == [
        ("3093", "Hệ điều hành (CO3093)", "CO3093")
    ]


def test_empty_and_malformed_my_courses_are_safe():
    assert parse_discovered_courses("<main>Nothing here</main>") == []
    assert parse_discovered_courses("<a href='broken'>") == []


def test_discovery_requests_only_authenticated_my_courses_page():
    static_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    session = FakeSession([FakeResponse(MY_COURSES_URL, static_html)])

    courses = discover_courses(session)

    assert len(courses) == 2
    assert [url for url, _kwargs in session.calls] == [MY_COURSES_URL]
    assert all("/my/" not in url or url.endswith("/my/courses.php") for url, _kwargs in session.calls)
    assert all("/course/index.php" not in url for url, _kwargs in session.calls)


def test_discovery_returns_empty_after_successful_static_page_without_courses():
    session = FakeSession([FakeResponse(MY_COURSES_URL, "<main>Loading...</main>")])

    assert discover_courses(session) == []


def test_zero_static_courses_trigger_rendered_browser_fallback():
    rendered_html = (FIXTURES / "dashboard_alternate.html").read_text(encoding="utf-8")
    session = FakeSession([FakeResponse(MY_COURSES_URL, "<main>Loading...</main>")])
    driver = FakeDriver(rendered_html)

    courses = discover_courses_with_browser_fallback(session, driver, browser_timeout=0)

    assert [course.course_id for course in courses] == ["3001", "3094"]
    assert driver.get_calls == [MY_COURSES_URL]
    assert driver.closed == ["temporary"]
    assert driver.current_window_handle == "original"


def test_rendered_my_courses_html_parses_and_restores_original_tab():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(rendered_html)

    courses = discover_courses_from_browser(driver, timeout=0)

    assert [course.course_id for course in courses] == ["2013", "1013"]
    assert driver.get_calls == [MY_COURSES_URL]
    assert driver.closed == ["temporary"]
    assert driver.current_window_handle == "original"
    assert driver.page_by_handle["original"] == "https://lms.hcmut.edu.vn/my/"


def test_browser_direct_anchor_fallback_handles_rendered_dom():
    driver = FakeDriver(
        anchors=[
            FakeAnchor("/course/view.php?id=1039", "Kỹ năng mềm (SP1039)"),
            FakeAnchor("/course/view.php?id=1039", "duplicate"),
        ]
    )

    courses = discover_courses_from_browser(driver, timeout=0)

    assert [(course.course_id, course.code) for course in courses] == [("1039", "SP1039")]
    assert driver.closed == ["temporary"]
    assert driver.current_window_handle == "original"


def test_browser_state_is_restored_when_rendered_discovery_raises():
    driver = FakeDriver(fail_get=True)

    with pytest.raises(RuntimeError, match="rendered discovery failed"):
        discover_courses_from_browser(driver, timeout=0)

    assert driver.closed == ["temporary"]
    assert driver.current_window_handle == "original"
    assert driver.page_by_handle["original"] == "https://lms.hcmut.edu.vn/my/"


def test_discovery_detects_expired_session_redirect():
    session = FakeSession([FakeResponse("https://lms.hcmut.edu.vn/login/index.php")])

    with pytest.raises(SessionExpiredError, match="đăng nhập"):
        discover_courses(session)


def test_discovery_failure_is_human_friendly():
    session = FakeSession([requests.Timeout()])

    with pytest.raises(CourseDiscoveryError, match="thêm course bằng URL"):
        discover_courses(session)
