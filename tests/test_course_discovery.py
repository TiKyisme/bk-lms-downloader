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
        self.driver.new_window_calls += 1
        if self.driver.new_window_behavior == "raise":
            raise RuntimeError("new tab failed")
        if self.driver.new_window_behavior == "none":
            return
        self.driver._create_temporary(switch=True)

    def window(self, handle):
        if handle not in self.driver.window_handles:
            raise RuntimeError(f"missing window: {handle}")
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
    def __init__(
        self,
        rendered_html="",
        *,
        fail_get=False,
        anchors=None,
        new_window_behavior="create",
        script_window_behavior="none",
        extra_handles=(),
        remove_temporary_during_get=False,
        remove_original_during_get=False,
    ):
        self.window_handles = ["original", *extra_handles]
        self.current_window_handle = "original"
        self.switch_to = FakeSwitchTo(self)
        self.rendered_html = rendered_html
        self.fail_get = fail_get
        self.anchors = anchors or []
        self.new_window_behavior = new_window_behavior
        self.script_window_behavior = script_window_behavior
        self.remove_temporary_during_get = remove_temporary_during_get
        self.remove_original_during_get = remove_original_during_get
        self.closed = []
        self.get_calls = []
        self.switched_to = []
        self.new_window_calls = 0
        self.page_by_handle = {
            handle: f"https://lms.hcmut.edu.vn/{handle}/"
            for handle in self.window_handles
        }
        self.page_by_handle["original"] = "https://lms.hcmut.edu.vn/my/"

    @property
    def page_source(self):
        return self.rendered_html

    @property
    def current_url(self):
        return self.page_by_handle.get(self.current_window_handle, "")

    def _create_temporary(self, *, switch):
        if "temporary" not in self.window_handles:
            self.window_handles.append("temporary")
            self.page_by_handle["temporary"] = "about:blank"
        if switch:
            self.current_window_handle = "temporary"

    def get(self, url):
        self.get_calls.append(url)
        if self.remove_temporary_during_get and "temporary" in self.window_handles:
            self.window_handles.remove("temporary")
        if self.remove_original_during_get and "original" in self.window_handles:
            self.window_handles.remove("original")
        if self.fail_get:
            raise RuntimeError("rendered discovery failed")
        self.page_by_handle[self.current_window_handle] = url

    def execute_script(self, script):
        if script == "return document.readyState":
            return "complete"
        if script == "window.open('about:blank', '_blank');":
            if self.script_window_behavior == "raise":
                raise RuntimeError("script tab failed")
            if self.script_window_behavior == "create":
                self._create_temporary(switch=False)
            return None
        raise AssertionError(f"Unexpected script: {script}")

    def find_elements(self, _by, selector):
        if selector == "a[href*='/course/view.php?id=']":
            return self.anchors
        return []

    def close(self):
        if self.current_window_handle not in self.window_handles:
            raise RuntimeError("cannot close missing window")
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


def test_verified_temporary_tab_is_the_only_tab_closed_and_all_original_tabs_remain():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(rendered_html, extra_handles=("course-tab",))

    discover_courses_from_browser(driver, timeout=0)

    assert driver.closed == ["temporary"]
    assert driver.window_handles == ["original", "course-tab"]
    assert driver.current_window_handle == "original"
    assert driver.page_by_handle["original"] == "https://lms.hcmut.edu.vn/my/"


def test_failed_new_tab_creation_uses_same_tab_without_closing_chrome_and_restores_url():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(
        rendered_html,
        new_window_behavior="none",
        script_window_behavior="none",
    )
    original_url = driver.current_url

    courses = discover_courses_from_browser(driver, timeout=0)

    assert [course.course_id for course in courses] == ["2013", "1013"]
    assert driver.closed == []
    assert driver.window_handles == ["original"]
    assert driver.current_window_handle == "original"
    assert driver.current_url == original_url
    assert driver.get_calls == [MY_COURSES_URL, original_url]


def test_script_tab_fallback_must_still_verify_a_real_new_handle_before_cleanup():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(
        rendered_html,
        new_window_behavior="raise",
        script_window_behavior="create",
    )

    discover_courses_from_browser(driver, timeout=0)

    assert driver.closed == ["temporary"]
    assert driver.current_window_handle == "original"


def test_missing_temporary_handle_never_closes_another_window():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(rendered_html, remove_temporary_during_get=True)

    courses = discover_courses_from_browser(driver, timeout=0)

    assert [course.course_id for course in courses] == ["2013", "1013"]
    assert driver.closed == []
    assert driver.window_handles == ["original"]
    assert driver.current_window_handle == "original"


def test_user_closed_temporary_tab_during_discovery_is_a_safe_empty_result():
    driver = FakeDriver(fail_get=True, remove_temporary_during_get=True)

    assert discover_courses_from_browser(driver, timeout=0) == []
    assert driver.closed == []
    assert driver.window_handles == ["original"]
    assert driver.current_window_handle == "original"


def test_missing_original_handle_never_closes_the_temporary_window():
    rendered_html = (FIXTURES / "dashboard_cards.html").read_text(encoding="utf-8")
    driver = FakeDriver(rendered_html, remove_original_during_get=True)

    discover_courses_from_browser(driver, timeout=0)

    assert driver.closed == []
    assert driver.window_handles == ["temporary"]
    assert driver.current_window_handle == "temporary"


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
