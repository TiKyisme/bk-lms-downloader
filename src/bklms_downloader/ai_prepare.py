from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable, Iterable

from .app_logging import get_logger
from .models import Course


LOG = get_logger(__name__)
AI_TOOL_RELATIVE_PATH = Path("tools") / "prepare_ai_course.py"
REQUIRED_AI_MODULES = {
    "beautifulsoup4": "bs4",
    "markdownify": "markdownify",
    "pypdf": "pypdf",
    "python-pptx": "pptx",
}


class OptionalAIDependenciesError(RuntimeError):
    """Raised only for an incomplete developer/source installation."""


class AIPreparationError(RuntimeError):
    pass


def missing_ai_dependencies(
    finder: Callable[[str], object | None] = importlib.util.find_spec,
) -> list[str]:
    """Return required local-preprocessing modules missing from this runtime."""
    return [package for package, module in REQUIRED_AI_MODULES.items() if finder(module) is None]


def default_ai_output(course_root: Path) -> Path:
    return course_root / "AI_Knowledge"


def default_ai_tool_path() -> Path:
    """Find the bundled tool in PyInstaller or the checkout in source mode."""
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parents[2]
    return root / AI_TOOL_RELATIVE_PATH


def _load_ai_pipeline(script_path: Path) -> ModuleType:
    """Load the bundled local pipeline without spawning Python or the GUI EXE."""
    spec = importlib.util.spec_from_file_location("_bklms_ai_pipeline", script_path)
    if spec is None or spec.loader is None:
        raise AIPreparationError("Không thể tải thành phần chuẩn bị AI.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    if not callable(getattr(module, "run_preparation", None)):
        raise AIPreparationError("Thành phần chuẩn bị AI không hợp lệ.")
    return module


class AICoursePreparer:
    """Run the bundled local pipeline for exactly one downloaded course."""

    def __init__(
        self,
        *,
        script_path: Path | None = None,
        dependency_finder: Callable[[str], object | None] = importlib.util.find_spec,
        pipeline_loader: Callable[[Path], ModuleType] = _load_ai_pipeline,
    ):
        self.script_path = script_path or default_ai_tool_path()
        self.dependency_finder = dependency_finder
        self.pipeline_loader = pipeline_loader
        self._pipeline: ModuleType | None = None

    def prepare(self, course_root: Path, output: Path | None = None) -> Path:
        missing = missing_ai_dependencies(self.dependency_finder)
        if missing:
            raise OptionalAIDependenciesError(
                "Thiếu thành phần AI cần thiết: " + ", ".join(missing) + "."
            )

        source_root = Path(course_root).expanduser().resolve()
        if not source_root.is_dir():
            raise AIPreparationError("Không tìm thấy thư mục course đã tải.")
        destination = Path(output or default_ai_output(source_root)).expanduser().resolve()
        expected_destination = default_ai_output(source_root).resolve()
        if destination != expected_destination:
            raise AIPreparationError("AI_Knowledge phải nằm trong thư mục course đã tải.")
        if not self.script_path.is_file():
            raise AIPreparationError("Không tìm thấy thành phần chuẩn bị AI trong ứng dụng.")

        try:
            pipeline = self._pipeline or self.pipeline_loader(self.script_path)
            self._pipeline = pipeline
            # The standalone tool prints Vietnamese CLI progress.  Redirect it
            # when embedded in the GUI so a Windows legacy console encoding can
            # never abort a local knowledge-base build.
            with redirect_stdout(io.StringIO()):
                pipeline.run_preparation(_pipeline_arguments(source_root, destination))
        except AIPreparationError:
            raise
        except Exception as exc:
            LOG.exception("AI preparation failed for %s", source_root)
            raise AIPreparationError("Không thể chuẩn bị course cho AI. Hãy thử lại sau.") from exc
        return destination


def _pipeline_arguments(course_root: Path, destination: Path) -> SimpleNamespace:
    """Keep GUI preparation local and deterministic: no transcription or cloud."""
    return SimpleNamespace(
        input=course_root,
        output=destination,
        include_references=False,
        transcribe=False,
        whisper_model="small",
        language=None,
        whisper_device="cpu",
        whisper_compute_type="int8",
        chunk_chars=4800,
        chunk_overlap=500,
        force=True,
    )


@dataclass(frozen=True)
class AICoursePreparationResult:
    course: Course
    output: Path | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.output is not None and self.error is None


@dataclass(frozen=True)
class AIBatchPreparationResult:
    results: list[AICoursePreparationResult]

    @property
    def succeeded(self) -> list[AICoursePreparationResult]:
        return [result for result in self.results if result.succeeded]

    @property
    def failed(self) -> list[AICoursePreparationResult]:
        return [result for result in self.results if not result.succeeded]


AIProgressCallback = Callable[[dict], None]
CourseRootResolver = Callable[[Course], Path]


class AIBatchPreparer:
    """Prepare independent per-course knowledge bases sequentially and safely."""

    def __init__(self, preparer_factory: Callable[[], AICoursePreparer] = AICoursePreparer):
        self.preparer_factory = preparer_factory

    def prepare_courses(
        self,
        courses: Iterable[Course],
        course_root_for: CourseRootResolver,
        progress_callback: AIProgressCallback | None = None,
    ) -> AIBatchPreparationResult:
        course_list = list(courses)
        if not course_list:
            return AIBatchPreparationResult([])

        preparer = self.preparer_factory()
        results: list[AICoursePreparationResult] = []
        total = len(course_list)
        for index, course in enumerate(course_list, start=1):
            self._emit(progress_callback, "ai_prepare_course_start", course=course, index=index, total=total)
            try:
                output = preparer.prepare(course_root_for(course))
                result = AICoursePreparationResult(course=course, output=output)
            except Exception as exc:
                LOG.exception("AI preparation failed for course %s", course.id)
                result = AICoursePreparationResult(
                    course=course,
                    error=_error_summary(exc),
                )
            results.append(result)
            self._emit(
                progress_callback,
                "ai_prepare_course_complete",
                result=result,
                index=index,
                total=total,
            )
        return AIBatchPreparationResult(results)

    @staticmethod
    def _emit(callback: AIProgressCallback | None, event: str, **payload) -> None:
        if callback is None:
            return
        try:
            callback({"event": event, **payload})
        except Exception:
            pass


def _error_summary(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if exc.__cause__ is not None:
        message += f" ({type(exc.__cause__).__name__}: {exc.__cause__})"
    return message
