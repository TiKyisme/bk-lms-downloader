import importlib
import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bklms_downloader.ai_prepare import (
    AIBatchPreparer,
    AICoursePreparer,
    AIPreparationError,
    REQUIRED_AI_MODULES,
    ai_runtime_diagnostics,
    default_ai_output,
    default_ai_tool_path,
    missing_ai_dependencies,
)
from bklms_downloader.models import Course


def make_course(tmp_path: Path, number: int, *, selected: bool = True) -> Course:
    return Course(
        id=f"course-{number}",
        url=f"https://lms.hcmut.edu.vn/course/view.php?id={number}",
        output=str(tmp_path / f"Course {number}"),
        name=f"Course {number} (CO{number:04d})",
        code=f"CO{number:04d}",
        selected=selected,
    )


def test_missing_runtime_dependencies_are_reported_from_actual_import_failures():
    def importer(module: str):
        if module == "pypdf":
            raise ModuleNotFoundError(module)
        return object()

    missing = missing_ai_dependencies(importer)
    assert missing == ["pypdf"]


def test_importable_dependency_is_not_rejected_when_spec_metadata_would_be_missing(monkeypatch):
    # This mirrors a PyInstaller runtime where metadata probing is unreliable
    # but importing the bundled module works normally.
    monkeypatch.setattr(importlib.util, "find_spec", lambda _module: None)
    assert missing_ai_dependencies(lambda _module: object()) == []


def test_required_runtime_ai_modules_are_importable():
    for module in REQUIRED_AI_MODULES.values():
        assert importlib.import_module(module) is not None


def test_existing_ai_knowledge_is_rebuilt_in_process_with_force(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    existing_output = default_ai_output(course_root)
    existing_output.mkdir()
    (existing_output / "stale.txt").write_text("stale", encoding="utf-8")
    script = tmp_path / "prepare_ai_course.py"
    script.write_text("# bundled helper", encoding="utf-8")
    calls = []
    pipeline = SimpleNamespace(run_preparation=lambda args: calls.append(args))
    preparer = AICoursePreparer(
        script_path=script,
        dependency_importer=lambda _module: object(),
        pipeline_loader=lambda _path: pipeline,
    )

    output = preparer.prepare(course_root)

    assert output == default_ai_output(course_root).resolve()
    assert calls[0].input == course_root.resolve()
    assert calls[0].output == output
    assert calls[0].force is True
    assert calls[0].transcribe is False


def test_preparer_protects_the_course_root_from_an_arbitrary_output_path(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    source_file = course_root / "slides.pdf"
    source_file.write_text("source", encoding="utf-8")
    preparer = AICoursePreparer(
        script_path=tmp_path / "missing.py",
        dependency_importer=lambda _module: object(),
    )

    with pytest.raises(AIPreparationError, match="AI_Knowledge"):
        preparer.prepare(course_root, tmp_path / "outside")

    assert source_file.read_text(encoding="utf-8") == "source"


def test_default_tool_path_uses_pyinstaller_resource_directory(monkeypatch, tmp_path: Path):
    resource = tmp_path / "tools" / "prepare_ai_course.py"
    resource.parent.mkdir()
    resource.write_text("# resource", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert default_ai_tool_path() == resource


def test_frozen_resource_pipeline_smoke_creates_ai_knowledge(monkeypatch, tmp_path: Path):
    resource = tmp_path / "tools" / "prepare_ai_course.py"
    resource.parent.mkdir()
    shutil.copy2(Path("tools") / "prepare_ai_course.py", resource)
    course_root = tmp_path / "Course"
    course_root.mkdir()
    (course_root / "content.txt").write_text("Bài giảng", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    output = AICoursePreparer().prepare(course_root)

    assert output == course_root / "AI_Knowledge"
    assert (output / "AI_TUTOR_CONTEXT.md").is_file()


def test_real_local_pipeline_creates_ai_knowledge_without_changing_source_files(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    source_file = course_root / "content.txt"
    source_file.write_text("Bài giảng cơ sở dữ liệu", encoding="utf-8")

    output = AICoursePreparer().prepare(course_root)

    assert (output / "AI_TUTOR_CONTEXT.md").is_file()
    assert (output / "meta" / "corpus.jsonl").is_file()
    assert source_file.read_text(encoding="utf-8") == "Bài giảng cơ sở dữ liệu"


def test_real_batch_path_creates_ai_knowledge_from_a_tiny_pdf(tmp_path: Path):
    from pypdf import PdfWriter

    course = make_course(tmp_path, 2013)
    course_root = Path(course.output)
    course_root.mkdir()
    (course_root / "notes.txt").write_text("Batch AI test", encoding="utf-8")
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with (course_root / "tiny.pdf").open("wb") as pdf_handle:
        writer.write(pdf_handle)

    batch = AIBatchPreparer().prepare_courses([course], lambda item: item.output_path)

    assert len(batch.succeeded) == 1
    assert batch.failed == []
    output = batch.succeeded[0].output
    assert output is not None
    assert (output / "AI_TUTOR_CONTEXT.md").is_file()


def test_runtime_diagnostics_report_actual_import_information():
    report = ai_runtime_diagnostics()

    assert "Frozen:" in report
    assert "pypdf (pypdf): IMPORT OK" in report
    assert "__file__:" in report
    assert "__spec__:" in report


class FakePreparer:
    def __init__(self, *, fail_names: set[str] | None = None):
        self.fail_names = fail_names or set()
        self.calls: list[Path] = []

    def prepare(self, course_root: Path) -> Path:
        self.calls.append(course_root)
        if course_root.name in self.fail_names:
            raise AIPreparationError("pipeline failed")
        return default_ai_output(course_root)


def test_batch_preparer_handles_one_and_multiple_courses_sequentially(tmp_path: Path):
    first, second = make_course(tmp_path, 2013), make_course(tmp_path, 3001)
    fake = FakePreparer()
    events = []
    manager = AIBatchPreparer(lambda: fake)

    result = manager.prepare_courses(
        [first, second],
        lambda course: Path(course.output),
        events.append,
    )

    assert fake.calls == [Path(first.output), Path(second.output)]
    assert [item.course.id for item in result.succeeded] == [first.id, second.id]
    assert result.failed == []
    assert [event["event"] for event in events] == [
        "ai_prepare_course_start",
        "ai_prepare_course_complete",
        "ai_prepare_course_start",
        "ai_prepare_course_complete",
    ]


def test_batch_preparer_handles_empty_course_list():
    manager = AIBatchPreparer(lambda: FakePreparer())

    assert manager.prepare_courses([], lambda course: Path(course.output)).results == []


def test_batch_preparer_continues_after_one_course_fails(tmp_path: Path):
    first, failed, third = (
        make_course(tmp_path, 2013),
        make_course(tmp_path, 3001),
        make_course(tmp_path, 3093),
    )
    fake = FakePreparer(fail_names={Path(failed.output).name})
    manager = AIBatchPreparer(lambda: fake)

    result = manager.prepare_courses(
        [first, failed, third],
        lambda course: Path(course.output),
    )

    assert fake.calls == [Path(first.output), Path(failed.output), Path(third.output)]
    assert [item.course.id for item in result.succeeded] == [first.id, third.id]
    assert [item.course.id for item in result.failed] == [failed.id]
    assert "AIPreparationError: pipeline failed" in result.failed[0].error


def test_batch_preparer_reports_when_all_courses_fail(tmp_path: Path):
    first, second = make_course(tmp_path, 2013), make_course(tmp_path, 3001)
    fake = FakePreparer(
        fail_names={Path(first.output).name, Path(second.output).name}
    )

    result = AIBatchPreparer(lambda: fake).prepare_courses(
        [first, second],
        lambda course: Path(course.output),
    )

    assert result.succeeded == []
    assert [item.course.id for item in result.failed] == [first.id, second.id]
