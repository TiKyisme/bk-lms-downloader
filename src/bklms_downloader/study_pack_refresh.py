"""Transactional Study Pack manifests, freshness checks, and optional exam enrichment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from .ai_study_pack import _included_pack_paths, validate_ai_study_pack, write_study_navigation
from .coursewave import CourseMatch, CoursewaveCandidate, CoursewaveClient, match_course
from .exam_sources import CachedExam, DriveItem, ExamCache, ExamCandidate, GoogleDriveProvider, drive_id, sha256_file
from .utils import safe_name
from .url_security import is_public_drive_url
from .zip_safety import safe_extract_zip


PACK_SCHEMA_VERSION = 1
PROCESSING_FINGERPRINT = "bklms-study-pack-v1.3"
SKIP_DIRS = {"AI_Knowledge", ".git", "__MACOSX", "node_modules"}
INTERNAL_METADATA_SOURCE_PATHS = {
    "_meta/course_structure.json",
    "_meta/download_manifest.json",
    "_meta/stats.json",
}


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    logical_path: str
    sha256: str
    size: int
    source_role: str = "course_material"


@dataclass(frozen=True)
class ExamAsset:
    stable_id: str
    original_name: str
    exam_type: str
    term: str
    sha256: str
    cache_path: str
    source_url: str
    source_role: str = "past_exam"
    extraction_status: str = "visual_unparsed"
    exam_variant: str = "unknown"


@dataclass(frozen=True)
class RefreshPlan:
    state: str
    new_sources: tuple[str, ...] = ()
    changed_sources: tuple[str, ...] = ()
    removed_sources: tuple[str, ...] = ()
    reused_sources: tuple[str, ...] = ()

    @property
    def requires_rebuild(self) -> bool:
        return self.state in {"missing", "legacy", "dirty"}


@dataclass
class EnrichmentResult:
    exams: list[ExamAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    match: CourseMatch | None = None
    stage: str = "not_requested"
    material_link_count: int = 0
    drive_source_count: int = 0
    drive_candidate_count: int = 0
    drive_states: dict[str, int] = field(default_factory=dict)
    authoritative: bool = False


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def snapshot_sources(root: Path) -> dict[str, SourceSnapshot]:
    root = Path(root).resolve()
    snapshots: dict[str, SourceSnapshot] = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.endswith("_AI_Study_Pack.zip") or path.name.endswith(" - AI Study Pack.zip"):
            continue
        logical = _relative(path, root)
        if logical.casefold() in INTERNAL_METADATA_SOURCE_PATHS:
            continue
        digest = sha256_file(path)
        if not digest:
            continue
        stable = hashlib.sha256(logical.encode("utf-8")).hexdigest()[:20]
        snapshots[logical] = SourceSnapshot(stable, logical, digest, path.stat().st_size)
    return snapshots


def _read_zip_json(pack: Path, member: str) -> dict | None:
    try:
        with zipfile.ZipFile(pack) as archive:
            return json.loads(archive.read(member).decode("utf-8"))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def exam_extraction_status(path: Path) -> str:
    if Path(path).suffix.lower() != ".pdf":
        return "visual_unparsed"
    try:
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        return "text_extracted" if len(text.strip()) >= 40 else "visual_unparsed"
    except Exception:
        return "visual_unparsed"


def plan_refresh(existing_pack: Path | None, source_root: Path) -> RefreshPlan:
    current = snapshot_sources(source_root)
    if existing_pack is None or not Path(existing_pack).is_file():
        return RefreshPlan("missing", new_sources=tuple(sorted(current)))
    manifest = _read_zip_json(Path(existing_pack), "meta/pack_manifest.json")
    source_manifest = _read_zip_json(Path(existing_pack), "meta/source_manifest.json")
    if not manifest or not source_manifest or manifest.get("processing_fingerprint") != PROCESSING_FINGERPRINT:
        return RefreshPlan("legacy", new_sources=tuple(sorted(current)))
    prior = {
        str(item.get("logical_path", "")): str(item.get("sha256", ""))
        for item in source_manifest.get("sources", [])
        if isinstance(item, dict)
    }
    new = sorted(path for path in current if path not in prior)
    changed = sorted(path for path, item in current.items() if path in prior and item.sha256 != prior[path])
    removed = sorted(path for path in prior if path not in current)
    reused = sorted(path for path, item in current.items() if prior.get(path) == item.sha256)
    state = "up_to_date" if not (new or changed or removed) else "dirty"
    return RefreshPlan(state, tuple(new), tuple(changed), tuple(removed), tuple(reused))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _archive_workspace(workspace: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in _included_pack_paths(workspace):
                archive.write(path, path.relative_to(workspace).as_posix())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _extract_pack(pack: Path, workspace: Path) -> None:
    with zipfile.ZipFile(pack) as archive:
        safe_extract_zip(archive, workspace)


class CoursewaveEnricher:
    """Optional Coursewave-to-public-Drive enrichment; failures remain warnings."""

    def __init__(
        self,
        *,
        catalog_client: CoursewaveClient | None = None,
        drive_provider: GoogleDriveProvider | None = None,
        cache: ExamCache | None = None,
    ):
        self.catalog_client = catalog_client or CoursewaveClient()
        self.drive_provider = drive_provider or GoogleDriveProvider()
        self.cache = cache or ExamCache()

    def enrich(
        self,
        *,
        course_code: str,
        course_name: str,
        cancel_event: Event | None = None,
        choose_candidate: Callable[[CourseMatch], CoursewaveCandidate | None] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> EnrichmentResult:
        result = EnrichmentResult()
        try:
            catalog_result = self.catalog_client.fetch_catalog_result()
            if catalog_result.status != "ok":
                reason = catalog_result.warnings[0] if catalog_result.warnings else "Không thể đọc danh mục HCMUT Coursewave."
                result.match = CourseMatch(catalog_result.status, "low", reason)
                result.warnings.append(reason)
                result.stage = catalog_result.status
                return result
            match = match_course(course_code=course_code, course_name=course_name, courses=catalog_result.courses)
            result.match = match
            if match.status in {"none", "no_match"}:
                result.warnings.append(match.reason)
                result.stage = "no_match"
                return result
            if match.status == "ambiguous":
                selected = choose_candidate(match) if choose_candidate else None
                if selected is None:
                    result.warnings.append("Đã bỏ qua Coursewave vì cần chọn môn phù hợp.")
                    result.stage = "ambiguous"
                    return result
                candidates = (selected,)
            else:
                candidates = match.candidates
            links = [
                DriveItem(link.url, link.label or link.url, is_folder="/folders/" in link.url, path_label="")
                for candidate in candidates
                for link in candidate.material_links
            ]
            deduped_links = {link.url: link for link in links}
            result.material_link_count = len(deduped_links)
            if not deduped_links:
                result.warnings.append("Coursewave đã khớp môn nhưng không có liên kết tài liệu công khai.")
                result.stage = "no_material_links"
                return result
            drive_links = [
                link for link in deduped_links.values()
                if drive_id(link.url) and is_public_drive_url(link.url)
            ]
            result.drive_source_count = len(drive_links)
            if not drive_links:
                result.warnings.append("Coursewave đã khớp môn nhưng không có liên kết Google Drive/Docs công khai.")
                result.stage = "no_public_drive_links"
                return result
            discovery = self.drive_provider.discover(drive_links, cancel_event=cancel_event, progress_callback=progress_callback)
            result.warnings.extend(discovery.warnings)
            result.drive_candidate_count = len(discovery.candidates)
            result.drive_states = dict(discovery.state_counts)
            result.authoritative = not any(
                discovery.state_counts.get(state)
                for state in ("http_fetch_failed", "permission_denied", "browser_render_failed", "timeout", "cancelled")
            )
            if not discovery.candidates:
                result.warnings.append("Không phát hiện tệp đề giữa kỳ/cuối kỳ công khai từ các nguồn Drive đã khớp.")
                if discovery.state_counts.get("permission_denied"):
                    result.stage = "permission_denied"
                elif discovery.state_counts.get("browser_render_failed"):
                    result.stage = "browser_render_failed"
                elif discovery.state_counts.get("timeout"):
                    result.stage = "timeout"
                elif discovery.state_counts.get("public_empty"):
                    result.stage = "public_empty"
                elif discovery.state_counts.get("public_enumerated"):
                    result.stage = "public_enumerated"
                else:
                    result.stage = "no_exam_candidates"
                return result
            seen_hashes: set[str] = set()
            for candidate in discovery.candidates:
                if cancel_event is not None and cancel_event.is_set():
                    result.warnings.append("Đã hủy bổ sung đề thi Coursewave.")
                    break
                cached = self.cache.get(candidate.stable_id)
                if cached is None:
                    stale_cached = self.cache.get(candidate.stable_id, max_age_seconds=None)
                    conditional_headers = {}
                    if stale_cached and stale_cached.etag:
                        conditional_headers["If-None-Match"] = stale_cached.etag
                    if stale_cached and stale_cached.last_modified:
                        conditional_headers["If-Modified-Since"] = stale_cached.last_modified
                    with tempfile.TemporaryDirectory(prefix="bklms_exam_download_") as temporary:
                        downloaded, etag, modified, warning = self.drive_provider.download(
                            candidate, Path(temporary), cancel_event=cancel_event, conditional_headers=conditional_headers or None
                        )
                        if downloaded is None and warning == "not_modified" and stale_cached is not None:
                            self.cache.touch(candidate.stable_id)
                            cached = self.cache.get(candidate.stable_id)
                        if downloaded is None and cached is None:
                            if warning:
                                result.warnings.append(warning)
                            result.drive_states["download_failed"] = result.drive_states.get("download_failed", 0) + 1
                            result.authoritative = False
                            continue
                        if downloaded is not None:
                            cached = self.cache.put(candidate.stable_id, downloaded, etag=etag, last_modified=modified)
                if cached.sha256 in seen_hashes:
                    continue
                seen_hashes.add(cached.sha256)
                result.exams.append(
                    ExamAsset(
                        stable_id=candidate.stable_id,
                        original_name=candidate.name,
                        exam_type=candidate.exam_type,
                        term=candidate.term,
                        sha256=cached.sha256,
                        cache_path=cached.path,
                        source_url=candidate.url,
                        extraction_status=exam_extraction_status(Path(cached.path)),
                        exam_variant=candidate.exam_variant,
                    )
                )
            result.stage = "completed"
        except Exception as exc:
            result.match = result.match or CourseMatch("fetch_failed", "low", "Không thể đọc danh mục HCMUT Coursewave.")
            result.warnings.append(f"Không thể bổ sung Coursewave: {type(exc).__name__}")
            result.stage = "fetch_failed"
        return result


class StudyPackRefresher:
    """Adds manifests/exams and atomically replaces only a known app-owned pack."""

    def finalize(
        self,
        *,
        candidate_pack: Path,
        final_pack: Path,
        source_root: Path,
        course_code: str,
        course_name: str,
        plan: RefreshPlan,
        exams: Iterable[ExamAsset] | None = None,
        enrichment: EnrichmentResult | None = None,
        cancel_event: Event | None = None,
    ) -> Path:
        with tempfile.TemporaryDirectory(prefix="bklms_pack_refresh_") as temporary:
            workspace = Path(temporary) / "pack"
            _extract_pack(candidate_pack, workspace)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Đã hủy cập nhật AI Study Pack.")
            preserved_exam_manifest = _read_zip_json(candidate_pack, "meta/exam_manifest.json") if exams is None else None
            preserve_existing_exams = exams is None and preserved_exam_manifest is not None
            exam_entries = list(exams or ())
            if not preserve_existing_exams:
                self._write_exam_assets(workspace, exam_entries)
            snapshots = snapshot_sources(source_root)
            records = _read_jsonl(workspace / "meta" / "documents.jsonl")
            chunks = _read_jsonl(workspace / "meta" / "corpus.jsonl")
            navigation_exams = [asdict(item) for item in exam_entries] if not preserve_existing_exams else list((preserved_exam_manifest or {}).get("exams", []))
            write_study_navigation(workspace, course_name, records, chunks, exams=navigation_exams)
            _write_json(workspace / "meta" / "source_manifest.json", {"schema_version": 1, "sources": [asdict(item) for item in snapshots.values()]})
            if not preserve_existing_exams:
                _write_json(
                    workspace / "meta" / "exam_manifest.json",
                    {
                    "schema_version": 1,
                    "provider": "HCMUT Coursewave",
                    "diagnostics": {
                        "stage": enrichment.stage if enrichment else "not_requested",
                        "coursewave_status": enrichment.match.status if enrichment and enrichment.match else "not_requested",
                        "material_link_count": enrichment.material_link_count if enrichment else 0,
                        "drive_source_count": enrichment.drive_source_count if enrichment else 0,
                        "drive_candidate_count": enrichment.drive_candidate_count if enrichment else 0,
                        "states": enrichment.drive_states if enrichment else {},
                        "warnings": enrichment.warnings if enrichment else [],
                        "authoritative": enrichment.authoritative if enrichment else False,
                    },
                    "exams": [
                        {
                            "stable_id": item.stable_id,
                            "original_name": item.original_name,
                            "exam_type": item.exam_type,
                            "exam_variant": item.exam_variant,
                            "term": item.term,
                            "sha256": item.sha256,
                            "source_url": item.source_url,
                            "source_role": item.source_role,
                            "extraction_status": item.extraction_status,
                            "retained_source_path": f"sources/past_exams/{item.stable_id}__{safe_name(item.original_name, 150)}",
                        }
                        for item in exam_entries
                    ],
                    },
                )
            _write_json(
                workspace / "meta" / "pack_manifest.json",
                {
                    "schema_version": PACK_SCHEMA_VERSION,
                    "builder_version": "1.3.0",
                    "processing_fingerprint": PROCESSING_FINGERPRINT,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "course": {"code": course_code, "name": course_name},
                    "refresh": asdict(plan),
                    "coursewave": {
                        "enabled": enrichment is not None,
                        "match": asdict(enrichment.match) if enrichment and enrichment.match else None,
                        "warnings": enrichment.warnings if enrichment else [],
                        "stage": enrichment.stage if enrichment else "not_requested",
                        "material_link_count": enrichment.material_link_count if enrichment else 0,
                        "drive_source_count": enrichment.drive_source_count if enrichment else 0,
                        "drive_states": enrichment.drive_states if enrichment else {},
                    },
                },
            )
            report = validate_ai_study_pack(workspace)
            if report.errors:
                raise RuntimeError("AI Study Pack validation failed: " + "; ".join(report.errors))
            final_pack.parent.mkdir(parents=True, exist_ok=True)
            _archive_workspace(workspace, final_pack)
        return final_pack

    @staticmethod
    def _write_exam_assets(workspace: Path, exams: list[ExamAsset]) -> None:
        shutil.rmtree(workspace / "sources" / "past_exams", ignore_errors=True)
        shutil.rmtree(workspace / "documents" / "past_exams", ignore_errors=True)
        exam_dir = workspace / "sources" / "past_exams"
        lines = ["# Past Exam Index", "", "Historical exams are assessment-style evidence, not course truth.", ""]
        for exam in exams:
            source = Path(exam.cache_path)
            filename = f"{exam.stable_id}__{safe_name(exam.original_name, 150)}"
            destination = exam_dir / filename
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            if exam.extraction_status == "text_extracted":
                try:
                    from pypdf import PdfReader

                    text = "\n".join(page.extract_text() or "" for page in PdfReader(source).pages).strip()
                    document = workspace / "documents" / "past_exams" / f"{exam.stable_id}.md"
                    document.parent.mkdir(parents=True, exist_ok=True)
                    document.write_text(
                        f"# {exam.original_name}\n\nSource role: `past_exam`\n\n{text}\n",
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            lines.extend(
                (
                    f"## `{exam.stable_id}` — {exam.original_name}",
                    "",
                    f"- Source role: `past_exam`",
                    f"- Type: `{exam.exam_type}`",
                    f"- Variant: `{exam.exam_variant}`",
                    f"- Term/year: `{exam.term or 'unknown'}`",
                    f"- SHA-256: `{exam.sha256}`",
                    f"- Extraction: `{exam.extraction_status}`",
                    f"- Retained source: `sources/past_exams/{filename}`",
                    "",
                )
            )
        if not exams:
            lines.append("_No accessible historical midterm/final exams were added._")
        (workspace / "06_EXAM_INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
