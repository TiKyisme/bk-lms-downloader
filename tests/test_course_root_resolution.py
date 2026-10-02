import json
from pathlib import Path

import pytest

from bklms_downloader.course_roots import CourseRootResolutionError, resolve_course_root
from bklms_downloader.models import Course
from bklms_downloader.utils import safe_name


def make_course(output: Path, *, name="DEMO9002 - Synthetic Course", url="https://lms.hcmut.edu.vn/course/view.php?id=9002"):
    return Course("course-demo-9002", url, str(output), name=name, code="DEMO9002")


def write_metadata(folder: Path, *, url: str | None, name: str = "DEMO9002 - Synthetic Course"):
    metadata_path = folder / "_meta" / "course_structure.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps({"root_course": name, "root_course_url": url, "courses": []}),
        encoding="utf-8",
    )
    return metadata_path


def test_exact_named_folder_with_matching_metadata_is_used(tmp_path: Path):
    course = make_course(tmp_path)
    expected = tmp_path / safe_name(course.name, 150)
    write_metadata(expected, url="https://lms.hcmut.edu.vn/course/view.php?lang=vi&id=9002")

    assert resolve_course_root(course) == expected


def test_shared_output_root_is_not_used_as_course_root_even_with_matching_metadata(tmp_path: Path):
    course = make_course(tmp_path)
    write_metadata(tmp_path, url=course.url)

    with pytest.raises(CourseRootResolutionError):
        resolve_course_root(course)


def test_metadata_url_selects_unique_folder_when_display_name_differs(tmp_path: Path):
    course = make_course(tmp_path)
    (tmp_path / "Old display name").mkdir()
    correct = tmp_path / "Downloaded name from LMS"
    write_metadata(correct, url="https://lms.hcmut.edu.vn/course/view.php?id=9002&lang=vi", name="Different title")

    assert resolve_course_root(course) == correct


def test_missing_course_does_not_fall_back_to_shared_parent_with_other_courses(tmp_path: Path):
    course = make_course(tmp_path)
    write_metadata(tmp_path / "DEMO9001 - Course A", url="https://lms.hcmut.edu.vn/course/view.php?id=9001")
    write_metadata(tmp_path / "DEMO9003 - Course C", url="https://lms.hcmut.edu.vn/course/view.php?id=9003")

    with pytest.raises(CourseRootResolutionError, match="DEMO9002") as error:
        resolve_course_root(course)

    assert str(tmp_path) not in str(error.value)


def test_exact_name_legacy_fallback_requires_no_metadata_children(tmp_path: Path):
    course = make_course(tmp_path)
    expected = tmp_path / safe_name(course.name, 150)
    expected.mkdir()
    (tmp_path / "another old course").mkdir()

    assert resolve_course_root(course) == expected


def test_mismatched_metadata_blocks_legacy_name_fallback(tmp_path: Path):
    course = make_course(tmp_path)
    expected = tmp_path / safe_name(course.name, 150)
    write_metadata(expected, url="https://lms.hcmut.edu.vn/course/view.php?id=9999", name=course.name)

    with pytest.raises(CourseRootResolutionError):
        resolve_course_root(course)


def test_duplicate_metadata_matches_are_ambiguous(tmp_path: Path):
    course = make_course(tmp_path)
    first = tmp_path / "download one"
    second = tmp_path / "download two"
    write_metadata(first, url=course.url)
    write_metadata(second, url=course.url)

    with pytest.raises(CourseRootResolutionError, match="nhiều thư mục"):
        resolve_course_root(course)


def test_missing_parent_fails_with_actionable_message_without_absolute_path(tmp_path: Path):
    course = make_course(tmp_path / "missing")

    with pytest.raises(CourseRootResolutionError, match="đồng bộ lại") as error:
        resolve_course_root(course)

    assert str(tmp_path) not in str(error.value)


def test_root_course_name_is_legacy_evidence_only_when_url_absent(tmp_path: Path):
    course = make_course(tmp_path)
    legacy = tmp_path / "legacy lms folder"
    write_metadata(legacy, url=None, name=course.name)

    assert resolve_course_root(course) == legacy
