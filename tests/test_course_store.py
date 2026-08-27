import json
from pathlib import Path

import pytest

from bklms_downloader.course_store import CourseStore
from bklms_downloader.models import CourseSyncResult


def course_url(course_id: int) -> str:
    return f"https://lms.hcmut.edu.vn/course/view.php?id={course_id}"


def test_empty_store_then_add_save_and_load_vietnamese_course(tmp_path: Path):
    path = tmp_path / "config" / "courses.json"
    store = CourseStore(path)

    assert store.list() == []
    course = store.add(
        course_url(3094),
        tmp_path / "Mạng máy tính",
        name="Mạng máy tính (TN) (CO3094)_NGUYỄN",
    )

    assert course.code == "CO3094"
    loaded = CourseStore(path).list()
    assert len(loaded) == 1
    assert loaded[0].name == "Mạng máy tính (TN) (CO3094)_NGUYỄN"
    assert loaded[0].output == str(tmp_path / "Mạng máy tính")


def test_duplicate_normalized_url_is_rejected(tmp_path: Path):
    store = CourseStore(tmp_path / "courses.json")
    store.add(course_url(123), tmp_path / "one")

    with pytest.raises(ValueError, match="đã có"):
        store.add(
            "https://LMS.HCMUT.EDU.VN/course/view.php?foo=ignored&id=123#section-2",
            tmp_path / "two",
        )


def test_edit_remove_and_sync_metadata(tmp_path: Path):
    store = CourseStore(tmp_path / "courses.json")
    course = store.add(course_url(3093), tmp_path / "old", name="Mạng máy tính (CO3093)")
    edited = store.edit(course.id, output=tmp_path / "new", name="Mạng máy tính")
    assert edited.output == str(tmp_path / "new")
    assert edited.code == ""

    result = CourseSyncResult(
        course_id=course.id,
        course_url=course.url,
        name="Mạng máy tính (CO3093)_Giảng viên",
        output=tmp_path / "new" / "Mạng máy tính",
        downloaded=3,
        skipped=14,
        errors=0,
        status="success",
    )
    updated = store.update_sync(course.id, result)
    assert updated.code == "CO3093"
    assert updated.last_status == "success"
    assert updated.last_downloaded == 3
    assert updated.last_sync

    removed = store.remove(course.id)
    assert removed.id == course.id
    assert CourseStore(store.path).list() == []


def test_remove_nonexistent_and_empty_remove_many_are_safe(tmp_path: Path):
    store = CourseStore(tmp_path / "courses.json")
    course = store.add(course_url(3093), tmp_path / "course", name="Mạng máy tính (CO3093)")

    assert store.remove("does-not-exist") is None
    assert store.remove_many([]) == []
    assert [item.id for item in store.list()] == [course.id]


def test_remove_many_persists_once_and_ignores_unknown_ids(tmp_path: Path, monkeypatch):
    store = CourseStore(tmp_path / "courses.json")
    first = store.add(course_url(3001), tmp_path / "first", name="Công nghệ phần mềm (CO3001)")
    second = store.add(course_url(3093), tmp_path / "second", name="Mạng máy tính (CO3093)")
    third = store.add(course_url(3094), tmp_path / "third", name="Mạng máy tính (CO3094)")
    save_calls = 0
    original_save = store.save

    def count_save():
        nonlocal save_calls
        save_calls += 1
        original_save()

    monkeypatch.setattr(store, "save", count_save)
    removed = store.remove_many([first.id, third.id, "does-not-exist", first.id])

    assert [course.id for course in removed] == [first.id, third.id]
    assert [course.id for course in store.list()] == [second.id]
    assert save_calls == 1
    assert [course.id for course in CourseStore(store.path).list()] == [second.id]


def test_clear_persists_an_empty_course_list(tmp_path: Path):
    path = tmp_path / "courses.json"
    store = CourseStore(path)
    store.add(course_url(3001), tmp_path / "first", name="Công nghệ phần mềm (CO3001)")
    store.add(course_url(3093), tmp_path / "second", name="Mạng máy tính (CO3093)")

    removed = store.clear()

    assert len(removed) == 2
    assert store.list() == []
    assert CourseStore(path).list() == []
    assert json.loads(path.read_text(encoding="utf-8"))["courses"] == []


def test_remove_operations_never_delete_downloaded_files_or_output_folders(tmp_path: Path):
    output = tmp_path / "downloads" / "Course A"
    output.mkdir(parents=True)
    slide = output / "slide.pdf"
    lecture = output / "lecture.docx"
    slide.write_text("slide", encoding="utf-8")
    lecture.write_text("lecture", encoding="utf-8")
    store = CourseStore(tmp_path / "courses.json")
    first = store.add(course_url(3001), output, name="Công nghệ phần mềm (CO3001)")
    second = store.add(course_url(3093), output, name="Mạng máy tính (CO3093)")

    assert store.remove(first.id) is not None
    assert output.is_dir() and slide.is_file() and lecture.is_file()
    assert [course.id for course in store.remove_many([second.id])] == [second.id]
    assert output.is_dir() and slide.is_file() and lecture.is_file()

    third = store.add(course_url(3094), output, name="Mạng máy tính (CO3094)")
    assert store.clear() == [third]
    assert output.is_dir() and slide.is_file() and lecture.is_file()


def test_corrupted_config_and_invalid_entries_do_not_crash(tmp_path: Path):
    path = tmp_path / "courses.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert CourseStore(path).list() == []

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "courses": [
                    {"id": "bad", "url": "https://example.com", "output": "D:/x"},
                    {"id": "good", "url": course_url(1), "output": "D:/x", "name": "Hợp lệ"},
                    {"id": "again", "url": course_url(1), "output": "D:/other"},
                ],
            }
        ),
        encoding="utf-8",
    )
    courses = CourseStore(path).list()
    assert [(course.id, course.name) for course in courses] == [("good", "Hợp lệ")]


def test_saved_schema_has_no_credentials_or_session_material(tmp_path: Path):
    path = tmp_path / "courses.json"
    store = CourseStore(path)
    store.add(course_url(3005), tmp_path / "PPL", name="Principles of Programming Languages")

    payload = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload).lower()
    assert payload["schema_version"] == 1
    assert "password" not in rendered
    assert "cookie" not in rendered
    assert "session" not in rendered
    assert "token" not in rendered
