from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence


OPTIONAL_AI_MODULES = {
    "markdownify": "markdownify",
    "pymupdf": "fitz",
    "python-pptx": "pptx",
}


class OptionalAIDependenciesError(RuntimeError):
    pass


class AIPreparationError(RuntimeError):
    pass


def missing_ai_dependencies(
    finder: Callable[[str], object | None] = importlib.util.find_spec,
) -> list[str]:
    return [package for package, module in OPTIONAL_AI_MODULES.items() if finder(module) is None]


def default_ai_output(course_root: Path) -> Path:
    return course_root / "AI_Knowledge"


class AICoursePreparer:
    """Thin optional bridge to the existing local AI course-preparation tool."""

    def __init__(
        self,
        *,
        script_path: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        dependency_finder: Callable[[str], object | None] = importlib.util.find_spec,
    ):
        self.script_path = script_path or (
            Path(__file__).resolve().parents[2] / "tools" / "prepare_ai_course.py"
        )
        self.runner = runner
        self.dependency_finder = dependency_finder

    def prepare(self, course_root: Path, output: Path | None = None) -> Path:
        missing = missing_ai_dependencies(self.dependency_finder)
        if missing:
            packages = ", ".join(missing)
            raise OptionalAIDependenciesError(
                f"Tính năng này cần cài thêm gói AI: {packages}. "
                "Cài bằng: pip install .[ai]"
            )
        if not course_root.is_dir():
            raise AIPreparationError("Không tìm thấy thư mục course đã tải.")
        if not self.script_path.is_file():
            raise AIPreparationError(
                "Không tìm thấy công cụ chuẩn bị AI. Hãy dùng bản cài từ source."
            )

        destination = output or default_ai_output(course_root)
        command: Sequence[str] = (
            sys.executable,
            str(self.script_path),
            "--input",
            str(course_root),
            "--output",
            str(destination),
            "--force",
        )
        try:
            completed = self.runner(command, check=False, capture_output=True, text=True)
        except OSError as exc:
            raise AIPreparationError("Không thể chạy công cụ chuẩn bị AI.") from exc
        if completed.returncode != 0:
            raise AIPreparationError("Không thể chuẩn bị course cho AI. Hãy thử lại sau.")
        return destination
