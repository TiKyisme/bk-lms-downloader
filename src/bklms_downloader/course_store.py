from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .models import Course, CourseSyncResult
from .platform_support import user_config_dir
from .utils import extract_course_code, is_course_url, normalized_course_url
from .app_logging import get_logger


SCHEMA_VERSION = 1
LOG = get_logger(__name__)


def default_courses_path() -> Path:
    """Choose a per-user configuration file without touching the repository."""
    return user_config_dir() / "courses.json"


class CourseStore:
    """Persistent, credential-free storage for the My Courses dashboard."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_courses_path()
        self._courses: list[Course] = []
        self.load()

    def load(self) -> list[Course]:
        """Load valid entries only; a damaged config starts as an empty list."""
        self._courses = []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._backup_corrupt_file()
            return self.list()
        except (OSError, UnicodeDecodeError):
            return self.list()

        if not isinstance(payload, dict) or not isinstance(payload.get("courses"), list):
            return self.list()

        seen: set[str] = set()
        for item in payload["courses"]:
            if not isinstance(item, dict):
                continue
            try:
                course = Course.from_dict(item)
            except Exception:
                continue
            if not course.id or not course.output or not is_course_url(course.url):
                continue
            identity = normalized_course_url(course.url)
            if identity in seen:
                continue
            seen.add(identity)
            course.url = identity
            if not course.code:
                course.code = extract_course_code(course.name) or ""
            self._courses.append(course)
        return self.list()

    def list(self) -> list[Course]:
        return list(self._courses)

    def get(self, course_id: str) -> Course | None:
        return next((course for course in self._courses if course.id == course_id), None)

    def add(
        self,
        url: str,
        output: Path | str,
        *,
        name: str = "",
        code: str = "",
        selected: bool = True,
    ) -> Course:
        normalized_url = self._validate_url(url)
        self._ensure_unique_url(normalized_url)
        output_raw = str(output).strip()
        if not output_raw:
            raise ValueError("Thư mục lưu không được để trống.")
        output_value = str(Path(output_raw).expanduser())
        course = Course(
            id=uuid.uuid4().hex,
            url=normalized_url,
            output=output_value,
            name=name.strip(),
            code=(code.strip().upper() or extract_course_code(name) or ""),
            selected=selected,
        )
        self._courses.append(course)
        self.save()
        return course

    def add_many(
        self,
        entries: Iterable[tuple[str, Path | str, str, str]],
    ) -> list[Course]:
        """Add multiple imported courses with one atomic persistence write.

        Existing URLs and duplicates within ``entries`` are skipped. Validation
        finishes before the in-memory list changes, and a failed save restores
        the original list so the GUI cannot show unpersisted imports.
        """
        known_urls = {normalized_course_url(course.url) for course in self._courses}
        prepared: list[Course] = []
        for url, output, name, code in entries:
            normalized_url = self._validate_url(url)
            if normalized_url in known_urls:
                continue
            output_raw = str(output).strip()
            if not output_raw:
                raise ValueError("Thư mục lưu không được để trống.")
            known_urls.add(normalized_url)
            prepared.append(
                Course(
                    id=uuid.uuid4().hex,
                    url=normalized_url,
                    output=str(Path(output_raw).expanduser()),
                    name=name.strip(),
                    code=(code.strip().upper() or extract_course_code(name) or ""),
                    selected=True,
                )
            )
        if not prepared:
            return []

        original = self._courses
        self._courses = [*original, *prepared]
        try:
            self.save()
        except Exception:
            self._courses = original
            raise
        return prepared

    def edit(self, course_id: str, **changes: object) -> Course:
        course = self._require(course_id)
        if "url" in changes:
            normalized_url = self._validate_url(str(changes["url"]))
            self._ensure_unique_url(normalized_url, except_id=course_id)
            course.url = normalized_url
        if "output" in changes:
            output_raw = str(changes["output"]).strip()
            if not output_raw:
                raise ValueError("Thư mục lưu không được để trống.")
            course.output = str(Path(output_raw).expanduser())
        if "name" in changes:
            course.name = str(changes["name"]).strip()
            if "code" not in changes:
                course.code = extract_course_code(course.name) or ""
        if "code" in changes:
            course.code = str(changes["code"]).strip().upper()
        if "selected" in changes:
            course.selected = bool(changes["selected"])
        self.save()
        return course

    def remove_many(self, course_ids: Iterable[str]) -> list[Course]:
        """Remove saved-course records in one persistence write, if any exist.

        Course output paths are metadata only.  This method intentionally never
        performs a filesystem deletion; downloaded documents stay untouched.
        """
        ids = {str(course_id) for course_id in course_ids}
        if not ids:
            return []
        removed = [course for course in self._courses if course.id in ids]
        if not removed:
            return []
        self._courses = [course for course in self._courses if course.id not in ids]
        self.save()
        return removed

    def clear(self) -> list[Course]:
        """Persist an empty saved-course list without deleting downloaded files."""
        removed = self.list()
        self._courses = []
        self.save()
        return removed

    def update_sync(self, course_id: str, result: CourseSyncResult) -> Course:
        course = self._require(course_id)
        course.last_sync = datetime.now().astimezone().isoformat(timespec="seconds")
        course.last_status = result.status
        course.last_downloaded = result.downloaded
        course.last_skipped = result.skipped
        course.last_errors = result.errors
        if result.name and result.name != "Chưa nhận diện":
            course.name = result.name
            detected_code = extract_course_code(course.name)
            if detected_code:
                course.code = detected_code
        if not course.code:
            course.code = extract_course_code(course.name) or ""
        self.save()
        return course

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "courses": [course.to_dict() for course in self._courses],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.stem}-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _validate_url(self, url: str) -> str:
        if not is_course_url(url):
            raise ValueError("URL course BK-LMS không hợp lệ.")
        return normalized_course_url(url)

    def _ensure_unique_url(self, url: str, except_id: str | None = None) -> None:
        if any(
            course.id != except_id and normalized_course_url(course.url) == url
            for course in self._courses
        ):
            raise ValueError("Course này đã có trong danh sách.")

    def _require(self, course_id: str) -> Course:
        course = self.get(course_id)
        if course is None:
            raise KeyError(f"Không tìm thấy course: {course_id}")
        return course

    def _backup_corrupt_file(self) -> None:
        if not self.path.is_file():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        try:
            shutil.copy2(self.path, backup)
            LOG.warning("Backed up corrupt course store to %s", backup)
        except OSError:
            pass
