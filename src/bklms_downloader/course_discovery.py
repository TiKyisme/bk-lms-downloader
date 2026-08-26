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
    """Inspect rendered My Courses without closing the student's Chrome window."""
    original_handle = _current_window_handle(driver)
    original_handles = _window_handles(driver)
    original_url = _current_url(driver)
    page_url = urljoin(base_url.rstrip("/") + "/", MY_COURSES_PATH.lstrip("/"))
    temporary_handle = _open_temporary_tab(driver, original_handle, original_handles)
    if temporary_handle is None:
        return _discover_from_original_tab(
            driver,
            original_handle,
            original_url,
            page_url,
            timeout,
        )

    try:
        if not _switch_to_window(driver, temporary_handle):
            return []
        driver.get(page_url)
        courses = _wait_for_rendered_courses(driver, page_url, timeout)
        if courses:
            return courses
        return _courses_from_browser_anchors(driver, page_url)
    except Exception:
        # A user may close a tab while Selenium is reading it.  Treat only that
        # case as an empty discovery result; other failures still reach the GUI's
        # existing friendly error path.
        current_handles = _window_handles(driver)
        if temporary_handle not in current_handles or original_handle not in current_handles:
            return []
        raise
    finally:
        _cleanup_temporary_tab(driver, original_handle, temporary_handle)


def _open_temporary_tab(
    driver,
    original_handle: str | None,
    original_handles: set[str],
) -> str | None:
    """Return a provably new temporary handle, or ``None`` for same-tab use."""
    if not original_handle or original_handle not in original_handles:
        return None

    try:
        driver.switch_to.new_window("tab")
    except Exception:
        pass

    temporary_handle = _verified_new_handle(driver, original_handle, original_handles)
    if temporary_handle is not None:
        return temporary_handle

    # Do not guess if new_window changed Chrome in an unexpected way. A new
    # handle not focused by Selenium could belong to a student action instead.
    handles_after_native = _window_handles(driver)
    if handles_after_native - original_handles:
        return None

    if not _switch_to_window(driver, original_handle):
        return None
    try:
        driver.execute_script("window.open('about:blank', '_blank');")
    except Exception:
        return None
    return _verified_new_handle(driver, original_handle, original_handles, allow_unfocused=True)


def _verified_new_handle(
    driver,
    original_handle: str,
    original_handles: set[str],
    *,
    allow_unfocused: bool = False,
) -> str | None:
    """Verify a single new handle before it can ever be closed later."""
    current_handles = _window_handles(driver)
    if original_handle not in current_handles:
        return None
    new_handles = current_handles - original_handles
    if not new_handles:
        return None

    current_handle = _current_window_handle(driver)
    if current_handle in new_handles:
        return current_handle
    if not allow_unfocused or len(new_handles) != 1:
        return None

    candidate = next(iter(new_handles))
    return candidate if _switch_to_window(driver, candidate) else None


def _discover_from_original_tab(
    driver,
    original_handle: str | None,
    original_url: str | None,
    page_url: str,
    timeout: float,
) -> list[DiscoveredCourse]:
    """Safe no-close fallback when Chrome cannot verify a new browser tab."""
    if not original_handle or original_handle not in _window_handles(driver):
        return []
    try:
        if not _switch_to_window(driver, original_handle):
            return []
        driver.get(page_url)
        courses = _wait_for_rendered_courses(driver, page_url, timeout)
        if courses:
            return courses
        return _courses_from_browser_anchors(driver, page_url)
    except Exception:
        if original_handle not in _window_handles(driver):
            return []
        raise
    finally:
        _restore_original_url(driver, original_handle, original_url)


def _cleanup_temporary_tab(
    driver,
    original_handle: str | None,
    temporary_handle: str | None,
) -> None:
    """Close only the verified disposable tab, never whichever tab is current."""
    if not original_handle or not temporary_handle or temporary_handle == original_handle:
        return
    handles = _window_handles(driver)
    if original_handle not in handles or temporary_handle not in handles:
        if original_handle in handles:
            _switch_to_window(driver, original_handle)
        return

    try:
        if not _switch_to_window(driver, temporary_handle):
            return
        handles = _window_handles(driver)
        if original_handle in handles and temporary_handle in handles:
            driver.close()
    except Exception:
        pass
    finally:
        if original_handle in _window_handles(driver):
            _switch_to_window(driver, original_handle)


def _restore_original_url(
    driver,
    original_handle: str | None,
    original_url: str | None,
) -> None:
    """Restore same-tab fallback navigation without touching any other window."""
    if not original_handle or not original_url or original_handle not in _window_handles(driver):
        return
    try:
        if _switch_to_window(driver, original_handle) and _current_url(driver) != original_url:
            driver.get(original_url)
    except Exception:
        pass


def _window_handles(driver) -> set[str]:
    try:
        return set(driver.window_handles)
    except Exception:
        return set()


def _current_window_handle(driver) -> str | None:
    try:
        return driver.current_window_handle
    except Exception:
        return None


def _current_url(driver) -> str | None:
    try:
        return driver.current_url
    except Exception:
        return None


def _switch_to_window(driver, handle: str) -> bool:
    try:
        driver.switch_to.window(handle)
        return True
    except Exception:
        return False


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
