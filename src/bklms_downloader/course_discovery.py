from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import LMS_BASE, REQUEST_TIMEOUT
from .utils import clean_text, extract_course_code, is_course_url, normalized_course_url


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
    """Extract enrolled courses from several common Moodle dashboard layouts."""
    soup = BeautifulSoup(html or "", "html.parser")
    discovered: dict[str, DiscoveredCourse] = {}
    for anchor in soup.select("a[href]"):
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
    return sorted(discovered.values(), key=lambda course: (course.code, course.name.casefold()))


def discover_courses(
    session: requests.Session,
    *,
    base_url: str = LMS_BASE,
    timeout: int = REQUEST_TIMEOUT,
) -> list[DiscoveredCourse]:
    """Fetch My courses defensively, without accessing anything beyond the session."""
    endpoints = ("/my/", "/course/index.php")
    errors: list[Exception] = []
    fetched_successfully = False
    all_courses: dict[str, DiscoveredCourse] = {}

    for endpoint in endpoints:
        try:
            response = session.get(urljoin(base_url + "/", endpoint.lstrip("/")), timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            errors.append(exc)
            continue

        if "/login/" in urlparse(response.url).path.lower():
            raise SessionExpiredError("Hãy đăng nhập lại BK-LMS.")
        fetched_successfully = True
        for course in parse_discovered_courses(response.text, response.url):
            all_courses.setdefault(course.url, course)

    if all_courses or fetched_successfully:
        return sorted(all_courses.values(), key=lambda course: (course.code, course.name.casefold()))
    raise CourseDiscoveryError("Không thể đọc danh sách môn học. Bạn vẫn có thể thêm course bằng URL.")


def _course_name(anchor) -> str:
    """Find a useful course title without relying on one Moodle theme selector."""
    containers: Iterable = (anchor, *anchor.parents)
    for container in containers:
        if getattr(container, "name", None) is None:
            continue
        for selector in (
            ".coursename",
            ".course-title",
            ".coursename a",
            "[data-region='course-content'] h3",
            "h3",
            "h4",
        ):
            node = container.select_one(selector)
            if node:
                value = clean_text(node.get_text(" ", strip=True))
                if value:
                    return value
        classes = " ".join(container.get("class", []))
        if any(marker in classes.lower() for marker in ("course-card", "coursebox", "course-item")):
            value = clean_text(container.get_text(" ", strip=True))
            if value:
                return value
    return clean_text(anchor.get_text(" ", strip=True))
