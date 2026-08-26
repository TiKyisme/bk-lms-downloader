from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import LMS_BASE, REQUEST_TIMEOUT
from .utils import clean_text, extract_course_code, is_course_url, normalized_course_url


MY_COURSES_PATH = "/my/courses.php"
_BROWSER_RENDER_TIMEOUT = 8.0
_BROWSER_COURSE_SELECTORS = (
    "a[href*='/course/view.php?id=']",
    ".course-card",
    ".dashboard-card",
    ".coursename",
    "[data-region='course-content']",
)
_COURSE_CONTEXT_MARKERS = (
    "course-card",
    "dashboard-card",
    "coursebox",
    "course-item",
    "course-content",
    "mycourse",
    "course-list",
    "coursename",
    "course-title",
)


@dataclass(frozen=True)
class DiscoveredCourse:
    url: str
    course_id: str
    name: str
    code: str = ""


class CourseDiscoveryError(RuntimeError):
    """A safe, human-facing failure to discover the user's accessible courses."""


class SessionExpiredError(CourseDiscoveryError):
    pass


def parse_discovered_courses(html: str, base_url: str = LMS_BASE) -> list[DiscoveredCourse]:
    """Extract course cards from the enrolled-course page, never navigation links."""
    soup = BeautifulSoup(html or "", "html.parser")
    discovered: dict[str, DiscoveredCourse] = {}
    for anchor in soup.select("a[href]"):
        if not _is_course_anchor(anchor):
            continue
        url = urljoin(base_url, anchor.get("href", ""))
        if not is_course_url(url):
            continue
        normalized_url = normalized_course_url(url)
        if normalized_url in discovered:
            continue
        name = _course_name(anchor)
        if not name:
            continue
        course_id = parse_qs(urlparse(normalized_url).query).get("id", [""])[0]
        discovered[normalized_url] = DiscoveredCourse(
            url=normalized_url,
            course_id=course_id,
            name=name,
            code=extract_course_code(name) or "",
        )
    return _sort_courses(discovered.values())


def discover_courses(
    session: requests.Session,
    *,
    base_url: str = LMS_BASE,
    timeout: int = REQUEST_TIMEOUT,
) -> list[DiscoveredCourse]:
    """Fetch only the authenticated BK-LMS enrolled-course listing.

    An empty result is deliberate: callers can then use the authenticated browser
    to inspect a page whose cards are rendered after the initial HTML response.
    """
    url = urljoin(base_url.rstrip("/") + "/", MY_COURSES_PATH.lstrip("/"))
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CourseDiscoveryError(
            "Không thể đọc danh sách môn học. Bạn vẫn có thể thêm course bằng URL."
        ) from exc

    if "/login/" in urlparse(response.url).path.lower():
        raise SessionExpiredError("Hãy đăng nhập lại BK-LMS.")
    return parse_discovered_courses(response.text, response.url)


def discover_courses_with_browser_fallback(
    session: requests.Session,
    driver,
    *,
    base_url: str = LMS_BASE,
    timeout: int = REQUEST_TIMEOUT,
    browser_timeout: float = _BROWSER_RENDER_TIMEOUT,
) -> list[DiscoveredCourse]:
    """Use rendered discovery only when the authenticated HTTP page has no cards."""
    courses = discover_courses(session, base_url=base_url, timeout=timeout)
    if courses:
        return courses
    return discover_courses_from_browser(driver, base_url=base_url, timeout=browser_timeout)


def discover_courses_from_browser(
    driver,
    *,
    base_url: str = LMS_BASE,
    timeout: float = _BROWSER_RENDER_TIMEOUT,
) -> list[DiscoveredCourse]:
    """Inspect rendered My Courses in a disposable tab without disturbing Chrome."""
    original_handle = driver.current_window_handle
    temporary_handle: str | None = None
    page_url = urljoin(base_url.rstrip("/") + "/", MY_COURSES_PATH.lstrip("/"))
    try:
        temporary_handle = _open_temporary_tab(driver, original_handle)
        driver.get(page_url)
        courses = _wait_for_rendered_courses(driver, page_url, timeout)
        if courses:
            return courses
        return _courses_from_browser_anchors(driver, page_url)
    finally:
        if temporary_handle is not None:
            try:
                driver.close()
            finally:
                # The original tab is never navigated, even if the fallback fails.
                driver.switch_to.window(original_handle)


def _open_temporary_tab(driver, original_handle: str) -> str:
    """Open a Selenium tab, with an execute_script fallback for older drivers."""
    previous_handles = set(driver.window_handles)
    try:
        driver.switch_to.new_window("tab")
    except (AttributeError, NotImplementedError):
        driver.execute_script("window.open('about:blank', '_blank');")
        new_handles = [handle for handle in driver.window_handles if handle not in previous_handles]
        if not new_handles:
            raise RuntimeError("Chrome did not create a temporary discovery tab.")
        driver.switch_to.window(new_handles[-1])

    temporary_handle = driver.current_window_handle
    if temporary_handle == original_handle:
        new_handles = [handle for handle in driver.window_handles if handle not in previous_handles]
        if not new_handles:
            raise RuntimeError("Chrome did not switch to a temporary discovery tab.")
        temporary_handle = new_handles[-1]
        driver.switch_to.window(temporary_handle)
    return temporary_handle


def _wait_for_rendered_courses(driver, page_url: str, timeout: float) -> list[DiscoveredCourse]:
    """Give Moodle's dynamic course cards a short, bounded chance to render."""
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        try:
            ready = driver.execute_script("return document.readyState") == "complete"
        except Exception:
            ready = True
        if ready:
            courses = parse_discovered_courses(getattr(driver, "page_source", ""), page_url)
            if courses:
                return courses
            if _has_likely_course_content(driver) and time.monotonic() >= deadline:
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    return parse_discovered_courses(getattr(driver, "page_source", ""), page_url)


def _has_likely_course_content(driver) -> bool:
    for selector in _BROWSER_COURSE_SELECTORS:
        try:
            if driver.find_elements("css selector", selector):
                return True
        except Exception:
            continue
    return False


def _courses_from_browser_anchors(driver, page_url: str) -> list[DiscoveredCourse]:
    """Last-resort DOM extraction for drivers that expose anchors before source."""
    discovered: dict[str, DiscoveredCourse] = {}
    try:
        anchors = driver.find_elements("css selector", "a[href*='/course/view.php?id=']")
    except Exception:
        return []
    for anchor in anchors:
        try:
            url = urljoin(page_url, anchor.get_attribute("href") or "")
            if not is_course_url(url):
                continue
            normalized_url = normalized_course_url(url)
            if normalized_url in discovered:
                continue
            name = clean_text(anchor.text or anchor.get_attribute("textContent") or "")
            if not name:
                continue
            course_id = parse_qs(urlparse(normalized_url).query).get("id", [""])[0]
            discovered[normalized_url] = DiscoveredCourse(
                url=normalized_url,
                course_id=course_id,
                name=name,
                code=extract_course_code(name) or "",
            )
        except Exception:
            continue
    return _sort_courses(discovered.values())


def _is_course_anchor(anchor) -> bool:
    """Avoid accepting course-view links from navigation, breadcrumbs, or search."""
    containers: Iterable = (anchor, *anchor.parents)
    for container in containers:
        if getattr(container, "name", None) is None:
            continue
        classes = " ".join(container.get("class", []))
        data_region = container.get("data-region", "")
        marker_source = f"{classes} {data_region}".lower()
        if any(marker in marker_source for marker in _COURSE_CONTEXT_MARKERS):
            return True
    return False


def _course_name(anchor) -> str:
    """Find a useful course title from the closest course-card/title context."""
    anchor_text = clean_text(anchor.get_text(" ", strip=True))
    containers: Iterable = (anchor, *anchor.parents)
    for container in containers:
        if getattr(container, "name", None) is None:
            continue
        classes = " ".join(container.get("class", []))
        class_source = classes.lower()
        if "coursename" in class_source or "course-title" in class_source:
            value = clean_text(container.get_text(" ", strip=True))
            if value:
                return value
        if any(marker in class_source for marker in _COURSE_CONTEXT_MARKERS):
            for selector in (".coursename", ".course-title", "h3", "h4"):
                node = container.select_one(selector)
                if node:
                    value = clean_text(node.get_text(" ", strip=True))
                    if value:
                        return value
            if anchor_text:
                return anchor_text
    return anchor_text


def _sort_courses(courses: Iterable[DiscoveredCourse]) -> list[DiscoveredCourse]:
    return sorted(courses, key=lambda course: (course.code, course.name.casefold()))
