"""Read-only HCMUT Coursewave catalog discovery and conservative course matching."""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .platform_support import user_config_dir
from .url_security import is_google_redirect_url, is_public_drive_url


COURSEWAVE_PUBLISHED_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQxYXne2cKmRBjWldPZ-B1ezPBDTKD34hL1Sfws6HEZQeba0g_4GrtVfmPDrOwHuA/pubhtml"
)
CATALOG_TIMEOUT = (5, 20)
CATALOG_CACHE_SECONDS = 6 * 60 * 60
CATALOG_CACHE_SCHEMA_VERSION = 2


def folded(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).strip().casefold()


def normalize_course_code(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    match = re.search(r"[A-Z]{1,5}\d{3,5}", text)
    return match.group(0) if match else ""


def normalize_course_name(value: str) -> str:
    text = folded(value)
    text = re.sub(r"\b(lop|class|nhom|group|nhom hoc|hoc ky|hk)\b.*$", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    # Published Sheets wraps outgoing links through a public Google redirect.
    # Store the destination, otherwise the Drive provider cannot recognize it.
    if is_google_redirect_url(value) and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q", [""])[0]
        if target:
            return canonical_url(target)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl()


def _material_key(value: str) -> str:
    """Deduplicate public Drive sources even when Sheets uses a /u/N URL."""
    url = canonical_url(value)
    parsed = urlparse(url)
    if is_public_drive_url(url):
        match = re.search(r"/(?:file|document|spreadsheets|presentation)/d/([^/?#]+)", parsed.path)
        if match:
            return f"drive-file:{match.group(1)}"
        match = re.search(r"/folders/([^/?#]+)", parsed.path)
        if match:
            return f"drive-folder:{match.group(1)}"
    return url


@dataclass(frozen=True)
class CoursewaveMaterial:
    url: str
    label: str = ""


@dataclass
class CoursewaveCourse:
    course_code: str
    course_name: str
    lecturer: str
    category: str
    material_links: list[CoursewaveMaterial] = field(default_factory=list)


@dataclass(frozen=True)
class CoursewaveCandidate:
    course_code: str
    course_name: str
    lecturers: tuple[str, ...]
    categories: tuple[str, ...]
    material_links: tuple[CoursewaveMaterial, ...]


@dataclass(frozen=True)
class CourseMatch:
    status: str
    confidence: str
    reason: str
    candidates: tuple[CoursewaveCandidate, ...] = ()


@dataclass(frozen=True)
class CoursewaveTabDiagnostic:
    name: str
    gid: str
    url: str
    http_status: int | None = None
    effective_url: str = ""
    table_count: int = 0
    parsed_course_rows: int = 0
    course_codes: tuple[str, ...] = ()
    warning: str = ""


@dataclass(frozen=True)
class CoursewaveCatalogResult:
    status: str
    courses: tuple[CoursewaveCourse, ...] = ()
    tabs: tuple[CoursewaveTabDiagnostic, ...] = ()
    warnings: tuple[str, ...] = ()


class CoursewaveCatalogError(RuntimeError):
    def __init__(self, result: CoursewaveCatalogResult):
        super().__init__(result.status)
        self.result = result


class CoursewaveCatalogCache:
    """Small per-user catalog metadata cache; it never stores Drive payloads."""

    def __init__(self, path: Path | None = None):
        self.path = path or (user_config_dir() / "coursewave-cache" / "catalog.json")

    def load(self, url: str, *, max_age_seconds: int = CATALOG_CACHE_SECONDS) -> list[CoursewaveCourse] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != CATALOG_CACHE_SCHEMA_VERSION:
                return None
            if payload.get("url") != url:
                return None
            if time.time() - float(payload.get("fetched_at", 0)) > max_age_seconds:
                return None
            return [
                CoursewaveCourse(
                    course_code=str(item.get("course_code", "")),
                    course_name=str(item.get("course_name", "")),
                    lecturer=str(item.get("lecturer", "")),
                    category=str(item.get("category", "")),
                    material_links=[CoursewaveMaterial(**link) for link in item.get("material_links", []) if isinstance(link, dict)],
                )
                for item in payload.get("courses", [])
                if isinstance(item, dict)
            ]
        except (OSError, ValueError, TypeError):
            return None

    def save(self, url: str, courses: Iterable[CoursewaveCourse]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CATALOG_CACHE_SCHEMA_VERSION,
            "url": url,
            "fetched_at": time.time(),
            "courses": [
                {
                    "course_code": item.course_code,
                    "course_name": item.course_name,
                    "lecturer": item.lecturer,
                    "category": item.category,
                    "material_links": [{"url": link.url, "label": link.label} for link in item.material_links],
                }
                for item in courses
            ],
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp") as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def _header_key(value: str) -> str | None:
    value = folded(value)
    if value in {"ma", "ma mon", "ma hp", "ma hoc phan", "course code", "course id"}:
        return "code"
    if value in {"ten mon", "ten mon hoc", "ten hoc phan", "course name"}:
        return "name"
    if value in {"giang vien", "lecturer", "gv"}:
        return "lecturer"
    if value in {"tai lieu", "material", "link", "video"}:
        return "material"
    return None


def _links(cell, base_url: str) -> list[CoursewaveMaterial]:
    found: list[CoursewaveMaterial] = []
    for anchor in cell.find_all("a", href=True):
        url = canonical_url(urljoin(base_url, anchor["href"]))
        if url:
            found.append(CoursewaveMaterial(url=url, label=anchor.get_text(" ", strip=True)))
    return found


def _table_grid(table) -> list[dict[int, object]]:
    """Return visual rows indexed by logical column, including rowspan cells."""
    pending: dict[int, tuple[object, int]] = {}
    grid_rows: list[dict[int, object]] = []
    for row in table.find_all("tr"):
        grid: dict[int, object] = {column: cell for column, (cell, _remaining) in pending.items()}
        next_pending: dict[int, tuple[object, int]] = {
            column: (cell, remaining - 1)
            for column, (cell, remaining) in pending.items()
            if remaining > 1
        }
        column = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while column in grid:
                column += 1
            colspan = max(1, int(cell.get("colspan", 1)))
            rowspan = max(1, int(cell.get("rowspan", 1)))
            for occupied in range(column, column + colspan):
                grid[occupied] = cell
                if rowspan > 1:
                    next_pending[occupied] = (cell, rowspan - 1)
            column += colspan
        pending = next_pending
        grid_rows.append(grid)
    return grid_rows


def _parse_coursewave_table(table, *, category: str, base_url: str) -> list[CoursewaveCourse]:
    rows = _table_grid(table)
    courses: list[CoursewaveCourse] = []
    header_index = None
    columns: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        candidate: dict[str, list[int]] = {}
        for position, cell in row.items():
            key = _header_key(cell.get_text(" ", strip=True))
            if key:
                candidate.setdefault(key, []).append(position)
        if "material" in candidate and ("code" in candidate or "name" in candidate):
            header_index = index
            columns = candidate
            break
    if header_index is None:
        return courses
    inherited = {"code": "", "name": "", "lecturer": ""}
    for row in rows[header_index + 1 :]:
        values = {
            key: [row[position] for position in positions if position in row]
            for key, positions in columns.items()
        }
        for key in inherited:
            text = next((cell.get_text(" ", strip=True) for cell in values.get(key, []) if cell.get_text(" ", strip=True)), "")
            if text:
                inherited[key] = text
        code = normalize_course_code(inherited["code"])
        name = inherited["name"].strip()
        links = [link for cell in values.get("material", []) for link in _links(cell, base_url)]
        if not (code or name) or not links:
            continue
        courses.append(
            CoursewaveCourse(
                course_code=code,
                course_name=name,
                lecturer=inherited["lecturer"].strip(),
                category=category,
                material_links=links,
            )
        )
    return courses


def parse_coursewave_table(html: str, *, category: str, base_url: str) -> list[CoursewaveCourse]:
    """Parse semantic columns while respecting merged cells and continuations."""
    soup = BeautifulSoup(html, "html.parser")
    courses: list[CoursewaveCourse] = []
    for table in soup.find_all("table"):
        courses.extend(_parse_coursewave_table(table, category=category, base_url=base_url))
    return courses


def discover_published_tabs(html: str, *, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    tabs: list[tuple[str, str]] = []
    seen: set[str] = set()
    # Google publishes the visible tab model in items.push(...) bootstrap
    # records, not as DOM anchors.  This is dynamic workbook metadata, not a
    # maintained gid list.
    item_pattern = re.compile(
        r'items\.push\(\{name:\s*"((?:\\.|[^"\\])*)".*?gid:\s*"([0-9]+)"',
        flags=re.DOTALL,
    )
    for match in item_pattern.finditer(html):
        try:
            name = ast.literal_eval(f'"{match.group(1)}"')
        except (SyntaxError, ValueError):
            name = f"Danh mục {match.group(2)}"
        gid = match.group(2)
        url = base_url.rstrip("/") + f"/sheet?gid={gid}&single=true"
        if gid not in seen:
            seen.add(gid)
            tabs.append((name.strip() or f"Danh mục {gid}", url))
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "gid=" not in href:
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        gid_match = re.search(r"gid=([0-9]+)", href)
        gid = gid_match.group(1) if gid_match else ""
        key = gid or canonical_url(url) + "#" + parsed.fragment
        if key in seen:
            continue
        seen.add(key)
        tabs.append((anchor.get_text(" ", strip=True) or "Danh mục", url))
    # Google Sheets pubhtml embeds tab IDs in bootstrap scripts rather than
    # normal anchors. The documented sheet endpoint renders a real table for
    # each discovered gid; no visual selector or fixed gid list is required.
    for gid in dict.fromkeys(re.findall(r"gid[^0-9]{0,80}([0-9]{3,})", html, flags=re.IGNORECASE)):
        url = base_url.rstrip("/") + f"/sheet?gid={gid}&single=true"
        if gid in seen:
            continue
        seen.add(gid)
        tabs.append((f"Danh mục {gid}", url))
    if not tabs:
        tabs.append(("Trang chính", base_url))
    return tabs


def aggregate_candidates(courses: Iterable[CoursewaveCourse]) -> tuple[CoursewaveCandidate, ...]:
    groups: dict[tuple[str, str], list[CoursewaveCourse]] = {}
    for course in courses:
        key = (normalize_course_code(course.course_code), normalize_course_name(course.course_name))
        if key == ("", ""):
            continue
        groups.setdefault(key, []).append(course)
    candidates: list[CoursewaveCandidate] = []
    for (code, _name_key), entries in groups.items():
        links: dict[str, CoursewaveMaterial] = {}
        for entry in entries:
            for link in entry.material_links:
                links.setdefault(_material_key(link.url), link)
        candidates.append(
            CoursewaveCandidate(
                course_code=code,
                course_name=next((entry.course_name for entry in entries if entry.course_name), ""),
                lecturers=tuple(sorted({entry.lecturer for entry in entries if entry.lecturer})),
                categories=tuple(sorted({entry.category for entry in entries if entry.category})),
                material_links=tuple(links.values()),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (item.course_code, folded(item.course_name))))


def match_course(*, course_code: str, course_name: str, courses: Iterable[CoursewaveCourse]) -> CourseMatch:
    candidates = aggregate_candidates(courses)
    code = normalize_course_code(course_code)
    if code:
        exact = tuple(candidate for candidate in candidates if candidate.course_code == code)
        if exact:
            return CourseMatch("matched", "high", "Khớp chính xác mã môn học.", exact)
    name = normalize_course_name(course_name)
    if not name:
        return CourseMatch("no_match", "low", "Không có mã hoặc tên môn học đáng tin cậy.")
    exact_name = tuple(candidate for candidate in candidates if normalize_course_name(candidate.course_name) == name)
    if len(exact_name) == 1:
        return CourseMatch("matched", "medium", "Khớp chính xác tên môn học.", exact_name)
    if len(exact_name) > 1:
        return CourseMatch("ambiguous", "low", "Có nhiều môn Coursewave cùng tên.", exact_name)
    if code:
        return CourseMatch("no_match", "low", f"Không tìm thấy môn {code} trên HCMUT Coursewave.")
    return CourseMatch("no_match", "low", "Không tìm thấy tên môn học trên HCMUT Coursewave.")


class CoursewaveClient:
    """Bounded read-only client for the published Coursewave workbook."""

    def __init__(self, session: requests.Session | None = None, *, timeout=CATALOG_TIMEOUT, cache: CoursewaveCatalogCache | None = None):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.cache = cache or CoursewaveCatalogCache()

    def _fetch_response(self, url: str) -> tuple[str, int, str]:
        response = self.session.get(url, timeout=self.timeout)
        try:
            response.raise_for_status()
            return response.text, response.status_code, response.url
        finally:
            response.close()

    def _fetch(self, url: str) -> str:
        return self._fetch_response(url)[0]

    def fetch_catalog_result(self, url: str = COURSEWAVE_PUBLISHED_URL, *, force_refresh: bool = False) -> CoursewaveCatalogResult:
        if not force_refresh:
            cached = self.cache.load(url)
            if cached is not None:
                return CoursewaveCatalogResult("ok", tuple(cached), warnings=("Đã dùng danh mục Coursewave lưu cục bộ.",))
        try:
            root_html, _root_status, _root_effective_url = self._fetch_response(url)
        except requests.RequestException as exc:
            return CoursewaveCatalogResult("fetch_failed", warnings=(f"Không thể đọc danh mục HCMUT Coursewave: {type(exc).__name__}.",))
        diagnostics: list[CoursewaveTabDiagnostic] = []
        all_courses: list[CoursewaveCourse] = []
        for category, tab_url in discover_published_tabs(root_html, base_url=url):
            gid_match = re.search(r"gid=([0-9]+)", tab_url)
            gid = gid_match.group(1) if gid_match else ""
            try:
                html, status, effective_url = self._fetch_response(tab_url) if tab_url != url else (root_html, _root_status, _root_effective_url)
                parsed = parse_coursewave_table(html, category=category, base_url=effective_url)
                all_courses.extend(parsed)
                diagnostics.append(CoursewaveTabDiagnostic(
                    category, gid, tab_url, status, effective_url, len(BeautifulSoup(html, "html.parser").find_all("table")),
                    len(parsed), tuple(sorted({item.course_code for item in parsed if item.course_code})),
                ))
            except requests.RequestException as exc:
                diagnostics.append(CoursewaveTabDiagnostic(category, gid, tab_url, warning=f"Không thể đọc tab: {type(exc).__name__}."))
        if not diagnostics or all(item.http_status is None for item in diagnostics):
            return CoursewaveCatalogResult("fetch_failed", tabs=tuple(diagnostics), warnings=("Không thể đọc danh mục HCMUT Coursewave.",))
        if not all_courses:
            return CoursewaveCatalogResult("catalog_parse_failed", tabs=tuple(diagnostics), warnings=("Không thể phân tích danh mục HCMUT Coursewave.",))
        self.cache.save(url, all_courses)
        return CoursewaveCatalogResult("ok", tuple(all_courses), tuple(diagnostics))

    def fetch_catalog(self, url: str = COURSEWAVE_PUBLISHED_URL, *, force_refresh: bool = False) -> list[CoursewaveCourse]:
        result = self.fetch_catalog_result(url, force_refresh=force_refresh)
        if result.status != "ok":
            raise CoursewaveCatalogError(result)
        return list(result.courses)
