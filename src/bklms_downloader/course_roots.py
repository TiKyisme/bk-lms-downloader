"""Resolve a course's downloaded directory without falling back to a shared parent."""

from __future__ import annotations

import json
from pathlib import Path
import re

from .models import Course
from .utils import normalized_course_url, safe_name


COURSE_STRUCTURE_RELATIVE = Path("_meta") / "course_structure.json"
MAX_COURSE_METADATA_BYTES = 1024 * 1024


class CourseRootResolutionError(ValueError):
    """A safe, user-actionable error when one course root cannot be identified."""


def _course_label(course: Course) -> str:
    return safe_name(course.code or course.name or "course", 40)


def _name_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _read_structure(folder: Path) -> tuple[bool, dict | None]:
    metadata_path = folder / COURSE_STRUCTURE_RELATIVE
    if not metadata_path.is_file():
        return False, None
    try:
        if metadata_path.stat().st_size > MAX_COURSE_METADATA_BYTES:
            return True, None
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True, None
    return True, value if isinstance(value, dict) else None


def _metadata_matches(course: Course, metadata: dict | None) -> bool:
    if metadata is None:
        return False
    root_url = str(metadata.get("root_course_url") or "").strip()
    if root_url:
        try:
            return normalized_course_url(root_url) == normalized_course_url(course.url)
        except (TypeError, ValueError):
            return False
    # Old metadata may have only a display name. Use it only when the URL field
    # is absent; a present-but-mismatched URL must never be overridden by a name.
    return bool(_name_key(course.name) and _name_key(metadata.get("root_course")) == _name_key(course.name))


def resolve_course_root(course: Course) -> Path:
    """Resolve one downloaded course using URL metadata, then an exact legacy name.

    The shared ``course.output_path`` is never returned. Only its exact named
    child or one direct child whose downloader metadata identifies ``course``
    can be selected.
    """
    output = course.output_path.expanduser().resolve()
    label = _course_label(course)
    if not output.is_dir():
        raise CourseRootResolutionError(
            f"Không tìm thấy thư mục tài liệu đã đồng bộ của {label}. "
            "Hãy đồng bộ lại môn này rồi thử lại."
        )

    expected = output / safe_name(course.name, 150) if course.name else None
    if expected is not None and expected.is_dir() and not expected.is_symlink():
        has_metadata, metadata = _read_structure(expected)
        if has_metadata and _metadata_matches(course, metadata):
            return expected

    output_has_metadata, _ = _read_structure(output)

    try:
        children = [
            child for child in output.iterdir()
            if child.is_dir()
            and not child.is_symlink()
            and child.resolve().parent == output
        ]
    except OSError:
        children = []
    metadata_children: list[tuple[Path, dict | None]] = []
    matches: list[Path] = []
    for child in children:
        has_metadata, metadata = _read_structure(child)
        if not has_metadata:
            continue
        metadata_children.append((child, metadata))
        if _metadata_matches(course, metadata):
            matches.append(child)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CourseRootResolutionError(
            f"Tìm thấy nhiều thư mục tài liệu cho {label}; để an toàn, hãy kiểm tra hoặc đồng bộ lại môn này."
        )

    # A missing/malformed/mismatched metadata file is not legacy evidence.
    # Name-based fallback is limited to old folders where no direct child has
    # downloader metadata at all.
    if not metadata_children and not output_has_metadata and expected is not None and expected.is_dir() and not expected.is_symlink():
        return expected

    raise CourseRootResolutionError(
        f"Không tìm thấy thư mục tài liệu đã đồng bộ của {label}. "
        "Hãy đồng bộ lại môn này rồi thử lại."
    )
