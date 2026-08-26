from pathlib import Path
from subprocess import CompletedProcess

import pytest

from bklms_downloader.ai_prepare import (
    AICoursePreparer,
    OptionalAIDependenciesError,
    default_ai_output,
    missing_ai_dependencies,
)


def test_missing_optional_dependencies_are_reported_without_importing_them():
    missing = missing_ai_dependencies(lambda module: None if module == "fitz" else object())

    assert missing == ["pymupdf"]


def test_preparer_degrades_gracefully_when_optional_packages_are_missing(tmp_path: Path):
    preparer = AICoursePreparer(dependency_finder=lambda _module: None)

    with pytest.raises(OptionalAIDependenciesError, match=r"pip install .\[ai\]"):
        preparer.prepare(tmp_path)


def test_preparer_reuses_existing_script_with_force_and_default_output(tmp_path: Path):
    course_root = tmp_path / "Course"
    course_root.mkdir()
    script = tmp_path / "prepare_ai_course.py"
    script.write_text("# helper", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    preparer = AICoursePreparer(
        script_path=script,
        runner=runner,
        dependency_finder=lambda _module: object(),
    )

    output = preparer.prepare(course_root)

    assert output == default_ai_output(course_root)
    assert calls[0][0][-1] == "--force"
    assert "--input" in calls[0][0]
    assert calls[0][1]["capture_output"]
