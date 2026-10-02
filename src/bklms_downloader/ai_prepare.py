from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import tempfile
import traceback
import zipfile
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable, Iterable

from .app_logging import get_logger
from .ai_study_pack import NAVIGATION_FILES, validate_ai_study_pack
from .ai_sources import inventory_course_sources
from .models import Course
from .study_pack_refresh import CoursewaveEnricher, StudyPackRefresher, plan_refresh
from .zip_safety import safe_extract_zip


LOG = get_logger(__name__)
AI_TOOL_RELATIVE_PATH = Path("tools") / "prepare_ai_course.py"
REQUIRED_AI_MODULES = {
    "beautifulsoup4": "bs4",
    "markdownify": "markdownify",
    "pypdf": "pypdf",
    "python-pptx": "pptx",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
}


class OptionalAIDependenciesError(RuntimeError):
    """Raised only for an incomplete developer/source installation."""


class AIPreparationError(RuntimeError):
    pass


class AIPreparationCancelled(AIPreparationError):
    """The learner cancelled before the current course became an archive."""


def missing_ai_dependencies(
    importer: Callable[[str], object] = importlib.import_module,
) -> list[str]:
    """Return modules that cannot actually import in this runtime.

    ``find_spec`` is deliberately not used here: a frozen PyInstaller process
    can import a bundled module even when metadata/spec probing is inconsistent.
    """
    missing: list[str] = []
    for package, module in REQUIRED_AI_MODULES.items():
        try:
            importer(module)
        except ImportError:
            missing.append(package)
    return missing


def default_ai_archive_destination(course_root: Path) -> Path:
    """Return the parent directory where the course ZIP is finalized."""
    return Path(course_root).expanduser().resolve().parent


def default_ai_tool_path() -> Path:
    """Find the bundled tool in PyInstaller or the checkout in source mode."""
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parents[2]
    return root / AI_TOOL_RELATIVE_PATH


def ai_runtime_diagnostics() -> str:
    """Collect import facts for support without using metadata to gate runtime."""
    lines = [
        f"Frozen: {'yes' if getattr(sys, 'frozen', False) else 'no'}",
        f"sys._MEIPASS: {getattr(sys, '_MEIPASS', None)!r}",
        f"sys.executable: {sys.executable}",
        f"AI tool: {default_ai_tool_path()} ({'OK' if default_ai_tool_path().is_file() else 'MISSING'})",
    ]
    for package, module_name in REQUIRED_AI_MODULES.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            lines.append(f"{package} ({module_name}): IMPORT FAILED: {type(exc).__name__}: {exc}")
            continue
        lines.extend(
            (
                f"{package} ({module_name}): IMPORT OK",
                f"  __file__: {getattr(module, '__file__', None)!r}",
                f"  __spec__: {getattr(module, '__spec__', None)!r}",
            )
        )
    return "\n".join(lines)


def _ai_runtime_self_test() -> Path:
    """Exercise the same batch path used by the end-user GUI."""
    missing = missing_ai_dependencies()
    if missing:
        raise RuntimeError("Missing packaged AI modules: " + ", ".join(missing))
    if not default_ai_tool_path().is_file():
        raise RuntimeError("Bundled AI preparation tool is missing")

    with tempfile.TemporaryDirectory(prefix="bklms_ai_smoke_") as temp_dir:
        base = Path(temp_dir)

        def seed_course(course_root: Path, title: str, marker: str) -> None:
            course_root.mkdir()
            (course_root / "notes.txt").write_text(marker, encoding="utf-8")
            html_dir = course_root / "Web Page"
            html_dir.mkdir()
            (html_dir / "content.html").write_text(
                f"<h1>{title}</h1><p>{marker}</p>",
                encoding="utf-8",
            )

            from pypdf import PdfWriter

            pdf_writer = PdfWriter()
            pdf_writer.add_blank_page(width=72, height=72)
            with (course_root / "tiny.pdf").open("wb") as pdf_handle:
                pdf_writer.write(pdf_handle)

            from pptx import Presentation

            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = f"{title} visual source"
            presentation.save(course_root / "tiny.pptx")

            from docx import Document

            word_document = Document()
            word_document.add_heading(f"{title} office source", level=1)
            word_document.add_paragraph(f"{marker} DOCX lecturer material explains one course concept.")
            table = word_document.add_table(rows=1, cols=2)
            table.rows[0].cells[0].text = "Topic"
            table.rows[0].cells[1].text = marker
            word_document.save(course_root / "tiny.docx")

            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Course data"
            sheet.append(["Source marker", marker])
            sheet.append(["Formula preserved", "=1+1"])
            workbook.save(course_root / "tiny.xlsx")

        specs = (
            ("A", "AI runtime course A", "PACKAGED_COURSE_A_ONLY"),
            ("B", "AI runtime course B", "PACKAGED_COURSE_B_ONLY"),
        )
        courses: list[Course] = []
        expected_markers: dict[str, str] = {}
        for suffix, title, marker in specs:
            course_root = base / f"Course {suffix}"
            seed_course(course_root, title, marker)
            courses.append(
                Course(
                    id=f"ai-self-test-{suffix.lower()}",
                    url=f"https://lms.hcmut.edu.vn/course/view.php?id={suffix}",
                    output=str(course_root),
                    name=title,
                )
            )
            expected_markers[title] = marker

        diagnostic = _load_ai_pipeline(default_ai_tool_path()).diagnose_course_directory(
            base / "Course A"
        )
        diagnostic_text = json.dumps(diagnostic, ensure_ascii=False)
        if not diagnostic.get("meaningful_lecturer_source_count"):
            raise RuntimeError("AI course diagnostic self-test found no teaching evidence")
        if str(base) in diagnostic_text or any(marker in diagnostic_text for marker in expected_markers.values()):
            raise RuntimeError("AI course diagnostic self-test leaked a path or source content")

        batch = AIBatchPreparer().prepare_courses(
            courses,
            lambda item: item.output_path,
        )
        pack_paths = [result.output for result in batch.succeeded if result.output is not None]
        if len(pack_paths) != 2 or batch.failed or batch.cancelled:
            detail = batch.failed[0].error if batch.failed else "wrong packaged batch result"
            raise RuntimeError("AI batch self-test failed: " + (detail or "unknown error"))
        if len(list(base.glob("*_AI_Study_Pack*.zip"))) != 2:
            raise RuntimeError("AI runtime self-test did not create exactly two ZIPs")
        if list(base.rglob("*.zip.part")):
            raise RuntimeError("AI runtime self-test left a partial ZIP")
        if any(path.name.casefold() == "ai_knowledge" for path in base.rglob("*")):
            raise RuntimeError("AI runtime self-test left legacy AI_Knowledge output")

        legacy_names = {
            "START_HERE.md",
            "COURSE_MAP.md",
            "TUTOR_PROTOCOL.md",
            "COVERAGE_REPORT.md",
            "AI_TUTOR_CONTEXT.md",
            "CHATGPT_START_PROMPT.txt",
        }
        for pack in pack_paths:
            if not pack.is_file() or pack.suffix.lower() != ".zip":
                raise RuntimeError("AI runtime self-test returned an invalid ZIP")
            with zipfile.ZipFile(pack) as archive:
                names = set(archive.namelist())
                if not all(name in names for name in NAVIGATION_FILES):
                    raise RuntimeError("AI runtime self-test did not create required navigation")
                if any(name in legacy_names for name in names):
                    raise RuntimeError("AI runtime self-test included legacy navigation")
                if not any(name.startswith("sources/") for name in names):
                    raise RuntimeError("AI runtime self-test did not retain source evidence")
                documents = archive.read("meta/documents.jsonl").decode("utf-8")
                if '"source_type": "word_document"' not in documents:
                    raise RuntimeError("AI runtime self-test did not extract DOCX sources")
                if '"source_type": "spreadsheet"' not in documents:
                    raise RuntimeError("AI runtime self-test did not extract XLSX sources")
                if not any(name.startswith("sources/") and name.lower().endswith(".docx") for name in names):
                    raise RuntimeError("AI runtime self-test did not retain the original DOCX")
                if not any(name.startswith("sources/") and name.lower().endswith(".xlsx") for name in names):
                    raise RuntimeError("AI runtime self-test did not retain the original XLSX")
                text = "\n".join(
                    archive.read(name).decode("utf-8", errors="replace")
                    for name in names
                    if name.lower().endswith((".md", ".txt", ".jsonl", ".json"))
                )
                own_marker = next(
                    marker for marker in expected_markers.values() if marker in text
                )
                other_markers = [
                    marker for marker in expected_markers.values() if marker != own_marker
                ]
                if any(marker in text for marker in other_markers):
                    raise RuntimeError("AI runtime self-test mixed course source data")
                if "=1+1" not in text:
                    raise RuntimeError("AI runtime self-test did not preserve spreadsheet formula text")
            with tempfile.TemporaryDirectory(prefix="bklms_ai_pack_roundtrip_") as unpacked:
                with zipfile.ZipFile(pack) as archive:
                    safe_extract_zip(archive, Path(unpacked))
                unpacked_validation = validate_ai_study_pack(Path(unpacked))
            if unpacked_validation.errors:
                raise RuntimeError(
                    "AI Study Pack ZIP round-trip failed: " + "; ".join(unpacked_validation.errors)
                )
        return pack_paths[0]


def run_ai_runtime_self_test() -> int:
    """Return a process exit code and persist diagnostics for windowed builds."""
    error_log = Path("ai-self-test-error.log")
    try:
        output = _ai_runtime_self_test()
    except Exception:
        error_log.write_text(
            ai_runtime_diagnostics() + "\n\n" + traceback.format_exc(),
            encoding="utf-8",
        )
        return 1
    error_log.unlink(missing_ok=True)
    Path("ai-self-test-diagnostics.log").write_text(
        ai_runtime_diagnostics()
        + f"\nSynthetic batch: OK\nAI Study Pack: {output}\n",
        encoding="utf-8",
    )
    return 0


def run_ai_runtime_diagnostics() -> int:
    """Write and print a concise report while exercising the full batch path."""
    report = ai_runtime_diagnostics()
    error_log = Path("ai-self-test-error.log")
    try:
        output = _ai_runtime_self_test()
    except Exception:
        error_log.write_text(
            report + "\n\n" + traceback.format_exc(),
            encoding="utf-8",
        )
        return 1
    error_log.unlink(missing_ok=True)
    report += f"\nSynthetic batch: OK\nAI Study Pack: {output}"
    Path("ai-self-test-diagnostics.log").write_text(report + "\n", encoding="utf-8")
    try:
        print(report)
    except (AttributeError, OSError, UnicodeError):
        pass
    return 0


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


def run_ai_course_diagnostic(course_folder: Path) -> dict:
    """Run the bundled safe, course-specific source diagnostic."""
    pipeline = _load_ai_pipeline(default_ai_tool_path())
    diagnostic = getattr(pipeline, "diagnose_course_directory", None)
    if not callable(diagnostic):
        raise AIPreparationError("The bundled AI source diagnostic is unavailable.")
    result = diagnostic(Path(course_folder))
    return result if isinstance(result, dict) else {}


class AICoursePreparer:
    """Run the bundled local pipeline for exactly one downloaded course."""

    def __init__(
        self,
        *,
        script_path: Path | None = None,
        dependency_importer: Callable[[str], object] = importlib.import_module,
        pipeline_loader: Callable[[Path], ModuleType] = _load_ai_pipeline,
    ):
        self.script_path = script_path or default_ai_tool_path()
        self.dependency_importer = dependency_importer
        self.pipeline_loader = pipeline_loader
        self._pipeline: ModuleType | None = None
        self.last_enrichment_warnings: tuple[str, ...] = ()
        self.last_source_warnings: tuple[str, ...] = ()
        self.last_source_inventory: dict = {}
        self.last_source_metrics: dict = {}
        self.last_refresh_state = "missing"

    def prepare(
        self,
        course_root: Path,
        output: Path | None = None,
        *,
        course_name: str | None = None,
        course_code: str = "",
        existing_pack: Path | None = None,
        enrich_exams: bool = False,
        coursewave_enricher: CoursewaveEnricher | None = None,
        choose_coursewave_candidate=None,
        coursewave_progress: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict], None] | None = None,
        cancel_event=None,
    ) -> Path:
        self.last_enrichment_warnings = ()
        self.last_source_warnings = ()
        self.last_source_inventory = {}
        self.last_source_metrics = {}
        self.last_refresh_state = "missing"
        missing = missing_ai_dependencies(self.dependency_importer)
        if missing:
            raise OptionalAIDependenciesError(
                "Thiếu thành phần AI cần thiết: " + ", ".join(missing) + "."
            )

        source_root = Path(course_root).expanduser().resolve()
        if not source_root.is_dir():
            raise AIPreparationError("Không tìm thấy thư mục course đã tải.")
        inventory = inventory_course_sources(source_root)
        self.last_source_inventory = inventory.to_dict()
        if inventory.lecturer_material_candidates == 0:
            if inventory.total_source_files == 0:
                raise AIPreparationError(
                    "Th\u01b0 m\u1ee5c course tr\u1ed1ng; kh\u00f4ng c\u00f3 t\u00e0i li\u1ec7u h\u1ecdc \u0111\u1ec3 t\u1ea1o Study Pack."
                )
            unsupported_types = Counter(
                Path(relative).suffix.lower() or "(kh\u00f4ng c\u00f3 ph\u1ea7n m\u1edf r\u1ed9ng)"
                for relative in inventory.unsupported_relative_paths
            )
            details = " \u2022 ".join(f"{extension}: {count}" for extension, count in sorted(unsupported_types.items()))
            if details:
                raise AIPreparationError(
                    "Course c\u00f3 t\u00e0i li\u1ec7u \u0111\u00e3 t\u1ea3i nh\u01b0ng ch\u01b0a c\u00f3 lo\u1ea1i file c\u00f3 th\u1ec3 x\u1eed l\u00fd. " + details
                )
            raise AIPreparationError("Kh\u00f4ng t\u00ecm th\u1ea5y t\u00e0i li\u1ec7u h\u1ecdc c\u00f3 th\u1ec3 x\u1eed l\u00fd trong course.")
        destination = Path(output or default_ai_archive_destination(source_root)).expanduser().resolve()
        if destination == source_root or source_root in destination.parents:
            raise AIPreparationError("Thư mục đích ZIP không được nằm trong course đã tải.")
        if destination == Path(destination.anchor) or destination == Path.home().resolve():
            raise AIPreparationError("Thư mục đích ZIP không hợp lệ.")
        if not self.script_path.is_file():
            raise AIPreparationError("Không tìm thấy thành phần chuẩn bị AI trong ứng dụng.")

        def report(phase: str, course_fraction: float, message: str = "", **payload) -> None:
            if progress_callback is None:
                return
            event = {
                "phase": phase,
                "course_fraction": course_fraction,
                "message": message,
                **payload,
            }
            try:
                progress_callback(event)
            except Exception:
                pass

        owned_pack = Path(existing_pack).expanduser().resolve() if existing_pack else None
        if owned_pack is not None and not owned_pack.is_file():
            owned_pack = None
        if owned_pack is None:
            owned_pack = self._find_owned_pack(destination, course_name or source_root.name)
        refresh_plan = plan_refresh(owned_pack, source_root)
        self.last_refresh_state = refresh_plan.state
        report(
            "source_preflight",
            0.03,
            "Đã kiểm kê tài liệu BK-LMS.",
            source_inventory=inventory.to_dict(),
        )
        report(
            "planning",
            0.04,
            "Đang lập kế hoạch cập nhật Study Pack...",
            refresh_state=refresh_plan.state,
        )
        enrichment = None
        if enrich_exams:
            def report_coursewave(message: str) -> None:
                report("coursewave", 0.06, message)
                if coursewave_progress is not None:
                    coursewave_progress(message)

            enrichment = (coursewave_enricher or CoursewaveEnricher()).enrich(
                course_code=course_code,
                course_name=course_name or source_root.name,
                cancel_event=cancel_event,
                choose_candidate=choose_coursewave_candidate,
                progress_callback=report_coursewave,
            )
            report("coursewave_complete", 0.15, "Đã kiểm tra Coursewave.")
        else:
            report("coursewave_skipped", 0.15, "Coursewave không được bật.")
        self.last_enrichment_warnings = tuple(enrichment.warnings) if enrichment else ()
        if refresh_plan.state == "up_to_date" and owned_pack is not None and not enrich_exams:
            report("validation", 0.98, "Đang kiểm tra Study Pack đã sẵn sàng.")
            self._read_pack_diagnostics(owned_pack)
            return owned_pack

        try:
            pipeline = self._pipeline or self.pipeline_loader(self.script_path)
            self._pipeline = pipeline
            # The standalone tool prints Vietnamese CLI progress.  Redirect it
            # when embedded in the GUI so a Windows legacy console encoding can
            # never abort a local knowledge-base build.
            if refresh_plan.requires_rebuild or owned_pack is None:
                with tempfile.TemporaryDirectory(prefix="bklms_pack_stage_") as temporary:
                    stage_destination = Path(temporary)
                    with redirect_stdout(io.StringIO()):
                        output_path = pipeline.run_preparation(
                            _pipeline_arguments(
                                source_root,
                                stage_destination,
                                course_name or source_root.name,
                                cancel_event,
                                existing_pack=owned_pack if refresh_plan.state == "dirty" else None,
                                refresh_plan=refresh_plan,
                                progress_callback=progress_callback,
                                source_inventory=inventory.to_dict(),
                            )
                        )
                    report("pipeline_complete", 0.95, "Đã hoàn tất sinh nội dung Study Pack.")
                    output_path = self._finalize_refresh(
                        candidate=output_path,
                        existing_pack=owned_pack,
                        destination=destination,
                        source_root=source_root,
                        course_code=course_code,
                        course_name=course_name or source_root.name,
                        refresh_plan=refresh_plan,
                        enrichment=enrichment,
                        cancel_event=cancel_event,
                    )
            else:
                report("validation", 0.96, "Đang kiểm tra Study Pack đã sẵn sàng.")
                output_path = self._finalize_refresh(
                    candidate=owned_pack,
                    existing_pack=owned_pack,
                    destination=destination,
                    source_root=source_root,
                    course_code=course_code,
                    course_name=course_name or source_root.name,
                    refresh_plan=refresh_plan,
                    enrichment=enrichment,
                    cancel_event=cancel_event,
                )
            report("finalization", 0.98, "Đã hoàn tất kiểm tra và đóng gói ZIP.")
        except AIPreparationCancelled:
            raise
        except AIPreparationError:
            raise
        except Exception as exc:
            if type(exc).__name__ == "PreparationCancelled":
                raise AIPreparationCancelled("Đã hủy chuẩn bị AI.") from exc
            if "No usable course teaching sources were included" in str(exc):
                extension_counts = self.last_source_inventory.get("extension_counts", {})
                detected_types = " • ".join(
                    f"{extension}: {count}"
                    for extension, count in sorted(extension_counts.items())
                ) if isinstance(extension_counts, dict) else ""
                if detected_types:
                    raise AIPreparationError(
                        "Kh\u00f4ng tr\u00edch xu\u1ea5t được bằng chứng học tập hữu ích. "
                        "Loại file đã phát hiện: " + detected_types
                    ) from exc
                raise AIPreparationError(
                    "Không tạo được AI Study Pack hữu ích: không đọc được tài liệu học trong course."
                ) from exc
            LOG.exception("AI preparation failed for %s", source_root)
            raise AIPreparationError("Không thể chuẩn bị course cho AI. Hãy thử lại sau.") from exc
        if not isinstance(output_path, Path) or output_path.suffix.lower() != ".zip":
            raise AIPreparationError("Chuẩn bị AI không tạo được ZIP hợp lệ.")
        self._read_pack_diagnostics(output_path)
        return output_path

    def _read_pack_diagnostics(self, pack_path: Path) -> None:
        try:
            with zipfile.ZipFile(pack_path) as archive:
                manifest = json.loads(archive.read("meta/pack_manifest.json").decode("utf-8"))
            inventory = manifest.get("source_inventory", {})
            metrics = manifest.get("source_metrics", {})
            if isinstance(inventory, dict):
                self.last_source_inventory = inventory
            self.last_source_metrics = metrics if isinstance(metrics, dict) else {}
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self.last_source_metrics = {}
            return

        warnings: list[str] = []
        error_count = int(self.last_source_metrics.get("source_error_count", 0) or 0)
        unsupported_count = int(self.last_source_metrics.get("unsupported_source_count", 0) or 0)
        if error_count:
            warnings.append(
                "Không đọc được " + str(error_count) + " tài liệu; các nguồn hợp lệ khác vẫn được giữ."
            )
        if unsupported_count:
            unsupported_types = Counter(
                Path(relative).suffix.lower() or "(không có phần mở rộng)"
                for relative in self.last_source_inventory.get("unsupported_relative_paths", [])
            )
            details = " • ".join(f"{extension}: {count}" for extension, count in sorted(unsupported_types.items()))
            warnings.append("Tài liệu chưa hỗ trợ" + (f" ({details})" if details else "") + ".")
        self.last_source_warnings = tuple(warnings)

    @staticmethod
    def _next_output_path(destination: Path, candidate: Path) -> Path:
        target = destination / candidate.name
        index = 2
        while target.exists():
            target = destination / f"{candidate.stem}_{index}{candidate.suffix}"
            index += 1
        return target

    @staticmethod
    def _find_owned_pack(destination: Path, course_name: str) -> Path | None:
        """Adopt only a manifest-identified v1.2 pack; never guess user ZIP ownership."""
        if not destination.is_dir():
            return None
        matches: list[Path] = []
        for candidate in destination.glob("*_AI_Study_Pack*.zip"):
            try:
                with zipfile.ZipFile(candidate) as archive:
                    manifest = json.loads(archive.read("meta/study_pack_manifest.json").decode("utf-8"))
                if manifest.get("course_name") == course_name and manifest.get("one_course_only") is True:
                    matches.append(candidate.resolve())
            except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                continue
        return matches[0] if len(matches) == 1 else None

    def _finalize_refresh(
        self,
        *,
        candidate: Path,
        existing_pack: Path | None,
        destination: Path,
        source_root: Path,
        course_code: str,
        course_name: str,
        refresh_plan,
        enrichment,
        cancel_event,
    ) -> Path:
        final_path = existing_pack or self._next_output_path(destination, candidate)
        exams = enrichment.exams if enrichment is not None and enrichment.authoritative else None
        return StudyPackRefresher().finalize(
            candidate_pack=candidate,
            final_pack=final_path,
            source_root=source_root,
            course_code=course_code,
            course_name=course_name,
            plan=refresh_plan,
            exams=exams,
            enrichment=enrichment,
            cancel_event=cancel_event,
        )


def _pipeline_arguments(
    course_root: Path,
    destination: Path,
    course_name: str,
    cancel_event=None,
    *,
    existing_pack: Path | None = None,
    refresh_plan=None,
    progress_callback: Callable[[dict], None] | None = None,
    source_inventory: dict | None = None,
) -> SimpleNamespace:
    """Keep GUI preparation local and deterministic: no transcription or cloud."""
    return SimpleNamespace(
        input=course_root,
        output=destination,
        archive_destination=destination,
        course_name=course_name,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
        source_inventory=source_inventory,
        incremental_existing_pack=existing_pack,
        incremental_reuse_paths=tuple(getattr(refresh_plan, "reused_sources", ())),
        incremental_stale_paths=tuple(
            [*getattr(refresh_plan, "changed_sources", ()), *getattr(refresh_plan, "removed_sources", ())]
        ),
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
    refresh_state: str = "missing"
    coursewave_enabled: bool = False
    warnings: tuple[str, ...] = ()
    source_warnings: tuple[str, ...] = ()
    source_inventory: dict = dataclass_field(default_factory=dict)
    source_metrics: dict = dataclass_field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.output is not None and self.error is None

    @property
    def succeeded_with_warnings(self) -> bool:
        return self.succeeded and bool(self.warnings or self.source_warnings)


@dataclass(frozen=True)
class AIBatchPreparationResult:
    results: list[AICoursePreparationResult]
    cancelled: bool = False

    @property
    def succeeded(self) -> list[AICoursePreparationResult]:
        return [result for result in self.results if result.succeeded]

    @property
    def failed(self) -> list[AICoursePreparationResult]:
        return [result for result in self.results if not result.succeeded]


AIProgressCallback = Callable[[dict], None]
CourseRootResolver = Callable[[Course], Path]


class AIBatchPreparer:
    """Prepare independent per-course ZIP archives sequentially and safely."""

    def __init__(self, preparer_factory: Callable[[], AICoursePreparer] = AICoursePreparer):
        self.preparer_factory = preparer_factory

    def prepare_courses(
        self,
        courses: Iterable[Course],
        course_root_for: CourseRootResolver,
        progress_callback: AIProgressCallback | None = None,
        cancel_event=None,
        enrich_exams: bool = False,
        coursewave_selector=None,
    ) -> AIBatchPreparationResult:
        course_list = list(courses)
        if not course_list:
            return AIBatchPreparationResult([])

        preparer = self.preparer_factory()
        results: list[AICoursePreparationResult] = []
        total = len(course_list)
        cancelled = False
        for index, course in enumerate(course_list, start=1):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            self._emit(progress_callback, "ai_prepare_course_start", course=course, index=index, total=total)
            try:
                try:
                    output = preparer.prepare(
                        course_root_for(course),
                        course_name=course.display_name,
                        course_code=course.code,
                        existing_pack=Path(course.study_pack_path) if course.study_pack_path else None,
                        enrich_exams=enrich_exams,
                        choose_coursewave_candidate=(
                            (lambda match: coursewave_selector(course, match, cancel_event))
                            if coursewave_selector is not None
                            else None
                        ),
                        coursewave_progress=(
                            lambda message: self._emit(
                                progress_callback,
                                "coursewave_progress",
                                course=course,
                                message=message,
                            )
                        ) if enrich_exams else None,
                        progress_callback=(
                            lambda progress: self._emit(
                                progress_callback,
                                "ai_prepare_progress",
                                course=course,
                                **progress,
                            )
                        ),
                        cancel_event=cancel_event,
                    )
                except TypeError as exc:
                    # Third-party/test preparers from v1.2 only accepted the
                    # stable course-name/cancellation boundary. Keep that
                    # compatibility while the built-in preparer receives the
                    # v1.3 refresh context above.
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    output = preparer.prepare(
                        course_root_for(course),
                        course_name=course.display_name,
                        cancel_event=cancel_event,
                    )
                result = AICoursePreparationResult(
                    course=course,
                    output=output,
                    refresh_state=getattr(preparer, "last_refresh_state", "missing"),
                    coursewave_enabled=enrich_exams,
                    warnings=tuple(getattr(preparer, "last_enrichment_warnings", ())),
                    source_warnings=tuple(getattr(preparer, "last_source_warnings", ())),
                    source_inventory=dict(getattr(preparer, "last_source_inventory", {}) or {}),
                    source_metrics=dict(getattr(preparer, "last_source_metrics", {}) or {}),
                )
            except AIPreparationCancelled:
                cancelled = True
                break
            except Exception as exc:
                LOG.exception("AI preparation failed for course %s", course.id)
                result = AICoursePreparationResult(
                    course=course,
                    error=_error_summary(exc),
                    refresh_state=getattr(preparer, "last_refresh_state", "missing"),
                    warnings=tuple(getattr(preparer, "last_enrichment_warnings", ())),
                    source_warnings=tuple(getattr(preparer, "last_source_warnings", ())),
                    source_inventory=dict(getattr(preparer, "last_source_inventory", {}) or {}),
                    source_metrics=dict(getattr(preparer, "last_source_metrics", {}) or {}),
                )
            results.append(result)
            self._emit(
                progress_callback,
                "ai_prepare_course_complete",
                result=result,
                index=index,
                total=total,
            )
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
        return AIBatchPreparationResult(results, cancelled=cancelled)

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
