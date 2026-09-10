import importlib
import shutil
import sys
import threading
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bklms_downloader.ai_prepare import (
    AIBatchPreparer,
    AICoursePreparer,
    AIPreparationError,
    REQUIRED_AI_MODULES,
    ai_runtime_diagnostics,
    default_ai_tool_path,
    missing_ai_dependencies,
    _ai_runtime_self_test,
)
from bklms_downloader.models import Course
from bklms_downloader.ai_study_pack import NAVIGATION_FILES


def load_cli_tool():
    spec = importlib.util.spec_from_file_location(
        "prepare_ai_course_cli", Path("tools") / "prepare_ai_course.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def cli_args(input_path: Path, output_path: Path, *, force: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        input=input_path,
        output=output_path,
        include_references=False,
        transcribe=False,
        whisper_model="small",
        language=None,
        whisper_device="cpu",
        whisper_compute_type="int8",
        chunk_chars=4800,
        chunk_overlap=500,
        force=force,
    )


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


def test_preparer_returns_one_zip_without_legacy_output(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    legacy = course_root / "AI_Knowledge"
    legacy.mkdir()
    sentinel = legacy / "user-owned.txt"
    sentinel.write_text("keep", encoding="utf-8")
    script = tmp_path / "prepare_ai_course.py"
    script.write_text("# bundled helper", encoding="utf-8")
    calls = []
    pack = tmp_path / "Course_AI_Study_Pack.zip"
    pipeline = SimpleNamespace(
        run_preparation=lambda args: calls.append(args) or pack,
    )
    preparer = AICoursePreparer(
        script_path=script,
        dependency_importer=lambda _module: object(),
        pipeline_loader=lambda _path: pipeline,
    )

    output = preparer.prepare(course_root)

    assert output == pack
    assert calls[0].input == course_root.resolve()
    assert calls[0].output == course_root.parent.resolve()
    assert calls[0].archive_destination == course_root.parent.resolve()
    assert calls[0].course_name == course_root.name
    assert calls[0].force is True
    assert calls[0].transcribe is False
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_preparer_protects_the_course_root_from_an_arbitrary_output_path(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    source_file = course_root / "slides.pdf"
    source_file.write_text("source", encoding="utf-8")
    preparer = AICoursePreparer(
        script_path=tmp_path / "missing.py",
        dependency_importer=lambda _module: object(),
    )

    with pytest.raises(AIPreparationError, match="không được nằm trong course"):
        preparer.prepare(course_root, course_root / "generated")

    assert source_file.read_text(encoding="utf-8") == "source"


@pytest.mark.parametrize("output_kind", ["same", "normalized_alias"])
def test_cli_force_rejects_input_overlap_before_deleting_anything(tmp_path: Path, output_kind: str):
    cli = load_cli_tool()
    course_root = tmp_path / "Course"
    course_root.mkdir()
    source_file = course_root / "keep.txt"
    source_file.write_text("source", encoding="utf-8")
    if output_kind == "same":
        output = course_root
    else:
        output = course_root / "AI_Knowledge" / ".."

    with pytest.raises(ValueError, match="input|ancestors"):
        cli.run_preparation(cli_args(course_root, output))

    assert source_file.read_text(encoding="utf-8") == "source"


def test_cli_missing_input_is_rejected_before_force_cleanup(tmp_path: Path):
    cli = load_cli_tool()
    output = tmp_path / "existing-output"
    output.mkdir()
    sentinel = output / "must-stay.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Input does not exist"):
        cli.run_preparation(cli_args(tmp_path / "missing", output))

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_default_tool_path_uses_pyinstaller_resource_directory(monkeypatch, tmp_path: Path):
    resource = tmp_path / "tools" / "prepare_ai_course.py"
    resource.parent.mkdir()
    resource.write_text("# resource", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert default_ai_tool_path() == resource


def test_frozen_resource_pipeline_smoke_creates_one_zip(monkeypatch, tmp_path: Path):
    resource = tmp_path / "tools" / "prepare_ai_course.py"
    resource.parent.mkdir()
    shutil.copy2(Path("tools") / "prepare_ai_course.py", resource)
    course_root = tmp_path / "Course"
    course_root.mkdir()
    (course_root / "content.txt").write_text("Bài giảng", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    output = AICoursePreparer().prepare(course_root)

    assert output == tmp_path / "Course_AI_Study_Pack.zip"
    assert not (course_root / "AI_Knowledge").exists()
    with zipfile.ZipFile(output) as archive:
        assert set(NAVIGATION_FILES).issubset(archive.namelist())


def test_real_local_pipeline_creates_one_zip_without_changing_source_files(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    source_file = course_root / "content.txt"
    source_file.write_text("Bài giảng cơ sở dữ liệu", encoding="utf-8")

    output = AICoursePreparer().prepare(course_root)

    assert output == tmp_path / "Course_AI_Study_Pack.zip"
    assert not (course_root / "AI_Knowledge").exists()
    with zipfile.ZipFile(output) as archive:
        assert set(NAVIGATION_FILES).issubset(archive.namelist())
        assert "meta/corpus.jsonl" in archive.namelist()
    assert source_file.read_text(encoding="utf-8") == "Bài giảng cơ sở dữ liệu"


def test_real_batch_path_creates_one_zip_from_a_tiny_pdf(tmp_path: Path):
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
    assert output is not None and output.suffix == ".zip"
    assert output.is_file()


def test_runtime_diagnostics_report_actual_import_information():
    report = ai_runtime_diagnostics()

    assert "Frozen:" in report
    assert "pypdf (pypdf): IMPORT OK" in report
    assert "__file__:" in report
    assert "__spec__:" in report


def test_runtime_self_test_covers_two_course_packaged_batch():
    output = _ai_runtime_self_test()

    assert output.name.endswith("_AI_Study_Pack.zip")


class FakePreparer:
    def __init__(self, *, fail_names: set[str] | None = None):
        self.fail_names = fail_names or set()
        self.calls: list[Path] = []

    def prepare(
        self,
        course_root: Path,
        *,
        course_name: str | None = None,
        cancel_event=None,
    ) -> Path:
        self.calls.append(course_root)
        if course_root.name in self.fail_names:
            raise AIPreparationError("pipeline failed")
        return course_root.parent / f"{course_root.name}_AI_Study_Pack.zip"


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


def _unpack(pack: Path, destination: Path) -> Path:
    with zipfile.ZipFile(pack) as archive:
        archive.extractall(destination)
    return destination


def test_bootstrap_protocol_and_resume_contract_is_explicit(tmp_path: Path):
    course_root = tmp_path / "Database"
    course_root.mkdir()
    (course_root / "Chapter 1 - Keys.md").write_text(
        "# Keys\n\n## Primary versus candidate keys\n\nSource-backed explanation.",
        encoding="utf-8",
    )

    pack = AICoursePreparer().prepare(course_root)
    unpacked = _unpack(pack, tmp_path / "unpacked")
    start = (unpacked / "00_START_HERE.md").read_text(encoding="utf-8").lower()
    protocol = (unpacked / "02_TUTOR_PROTOCOL.md").read_text(encoding="utf-8").lower()
    resume = (unpacked / "05_RESUME_STATE.md").read_text(encoding="utf-8")

    for name in NAVIGATION_FILES[1:]:
        assert name.lower() in start
    for phrase in (
        "first unresolved",
        "do not ask",
        "teach",
        "understanding check",
    ):
        assert phrase in start
    for phrase in (
        "teach",
        "assess",
        "wait",
        "debug",
        "re-assess",
        "mastery",
        "coverage",
        "source_id",
        "outside supplied course material",
        "theory dump",
        "before the learner responds",
    ):
        assert phrase in protocol
    assert "Current chapter:" in resume
    assert "Next topic:" in resume


def test_multiple_course_batch_isolated_and_continues_after_failure(tmp_path: Path):
    first, failed, third = (
        make_course(tmp_path, 1001),
        make_course(tmp_path, 1002),
        make_course(tmp_path, 1003),
    )

    class ArchivePreparer:
        def prepare(self, course_root: Path, *, course_name: str, cancel_event=None) -> Path:
            if course_root.name == "Course 1002":
                raise AIPreparationError("synthetic failure")
            pack = course_root.parent / f"{course_name}_AI_Study_Pack.zip"
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("00_START_HERE.md", f"course={course_name}")
                archive.writestr("sources/course.txt", f"only={course_name}")
            return pack

    result = AIBatchPreparer(lambda: ArchivePreparer()).prepare_courses(
        [first, failed, third],
        lambda course: Path(course.output),
    )

    assert len(result.succeeded) == 2
    assert len(result.failed) == 1
    packs = sorted(tmp_path.glob("*_AI_Study_Pack.zip"))
    assert [pack.name for pack in packs] == [
        "Course 1001 (CO1001)_AI_Study_Pack.zip",
        "Course 1003 (CO1003)_AI_Study_Pack.zip",
    ]
    for pack in packs:
        with zipfile.ZipFile(pack) as archive:
            content = "\n".join(archive.read(name).decode() for name in archive.namelist())
        assert "Course 1002" not in content
        assert pack.stem.split("_AI_Study_Pack")[0] in content


def test_cancelled_batch_keeps_completed_zip_and_skips_remaining(tmp_path: Path):
    first, second = make_course(tmp_path, 1101), make_course(tmp_path, 1102)
    cancel_event = threading.Event()

    class CancelAfterFirst:
        def __init__(self):
            self.calls = []

        def prepare(self, course_root: Path, *, course_name: str, cancel_event=None) -> Path:
            self.calls.append(course_root)
            pack = course_root.parent / f"{course_name}_AI_Study_Pack.zip"
            pack.write_bytes(b"completed")
            cancel_event.set()
            return pack

    fake = CancelAfterFirst()
    result = AIBatchPreparer(lambda: fake).prepare_courses(
        [first, second], lambda course: Path(course.output), cancel_event=cancel_event
    )

    assert result.cancelled
    assert [path.name for path in fake.calls] == ["Course 1101"]
    assert (tmp_path / "Course 1101 (CO1101)_AI_Study_Pack.zip").read_bytes() == b"completed"
    assert not (tmp_path / "Course 1102 (CO1102)_AI_Study_Pack.zip").exists()


def test_failed_generation_leaves_no_archive_part_or_persistent_workspace(tmp_path: Path):
    course_root = tmp_path / "Failure Course"
    course_root.mkdir()
    script = tmp_path / "prepare_ai_course.py"
    script.write_text("# bundled helper", encoding="utf-8")

    def fail(_args):
        raise RuntimeError("synthetic extraction failure")

    preparer = AICoursePreparer(
        script_path=script,
        dependency_importer=lambda _module: object(),
        pipeline_loader=lambda _path: SimpleNamespace(run_preparation=fail),
    )
    with pytest.raises(AIPreparationError):
        preparer.prepare(course_root)

    assert list(tmp_path.glob("*.zip")) == []
    assert list(tmp_path.glob("*.zip.part")) == []
    assert not (course_root / "AI_Knowledge").exists()


def test_existing_collision_is_not_overwritten_and_metadata_has_no_private_paths(tmp_path: Path):
    course_root = tmp_path / "Collision Course"
    course_root.mkdir()
    (course_root / "notes.txt").write_text("source text", encoding="utf-8")
    legacy = course_root / "AI_Knowledge"
    legacy.mkdir()
    (legacy / "user-owned.txt").write_text("must survive", encoding="utf-8")
    existing = tmp_path / "Collision Course_AI_Study_Pack.zip"
    existing.write_bytes(b"user-owned archive")

    generated = AICoursePreparer().prepare(course_root)

    assert generated.name == "Collision Course_AI_Study_Pack_2.zip"
    assert existing.read_bytes() == b"user-owned archive"
    assert (legacy / "user-owned.txt").read_text(encoding="utf-8") == "must survive"
    unpacked = _unpack(generated, tmp_path / "collision-unpacked")
    for path in [*(unpacked / name for name in NAVIGATION_FILES), *(unpacked / "meta").glob("*")]:
        if path.is_file():
            assert str(tmp_path) not in path.read_text(encoding="utf-8", errors="replace")
