import json
import os
import zipfile
from pathlib import Path

import pytest

from bklms_downloader.ai_prepare import AICoursePreparer
from bklms_downloader.study_pack_refresh import (
    CoursewaveEnricher,
    ExamAsset,
    EnrichmentResult,
    RefreshPlan,
    StudyPackRefresher,
    plan_refresh,
    snapshot_sources,
)


def test_source_snapshot_and_refresh_plan_detect_changes(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    source = root / "notes.txt"
    source.write_text("first", encoding="utf-8")
    initial = snapshot_sources(root)
    assert list(initial) == ["notes.txt"]

    legacy = tmp_path / "legacy.zip"
    legacy.write_bytes(b"not a pack")
    assert plan_refresh(legacy, root).state == "legacy"

    source.write_text("changed", encoding="utf-8")
    plan = plan_refresh(None, root)
    assert plan.state == "missing"
    assert plan.new_sources == ("notes.txt",)


def test_source_snapshot_excludes_downloader_internal_metadata(tmp_path: Path):
    root = tmp_path / "Course"
    metadata = root / "_meta"
    metadata.mkdir(parents=True)
    (root / "notes.txt").write_text("course material", encoding="utf-8")
    for name in ("course_structure.json", "download_manifest.json", "stats.json"):
        (metadata / name).write_text("{}", encoding="utf-8")

    snapshots = snapshot_sources(root)

    assert set(snapshots) == {"notes.txt"}


def test_refresh_manifest_is_private_and_unchanged_pack_is_reused(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("source-backed content", encoding="utf-8")
    pack = AICoursePreparer().prepare(root, course_code="CO2013")

    plan = plan_refresh(pack, root)
    assert plan.state == "up_to_date"
    assert plan.reused_sources == ("notes.txt",)
    with zipfile.ZipFile(pack) as archive:
        manifest = json.loads(archive.read("meta/pack_manifest.json"))
        sources = json.loads(archive.read("meta/source_manifest.json"))
        assert manifest["course"]["code"] == "CO2013"
        assert sources["sources"][0]["sha256"]
        assert str(tmp_path) not in archive.read("meta/source_manifest.json").decode("utf-8")
        assert "06_EXAM_INDEX.md" in archive.namelist()


def test_unchanged_manifest_enabled_pack_skips_pipeline_processing(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("source-backed content", encoding="utf-8")
    pack = AICoursePreparer().prepare(root)
    calls = []

    class Pipeline:
        def run_preparation(self, _args):
            calls.append(True)
            raise AssertionError("unchanged sources must not be reprocessed")

    preparer = AICoursePreparer(
        script_path=Path("tools") / "prepare_ai_course.py",
        dependency_importer=lambda _module: object(),
        pipeline_loader=lambda _path: Pipeline(),
    )
    output = preparer.prepare(root, existing_pack=pack)

    assert output == pack
    assert calls == []


def test_refresh_plan_reports_added_changed_and_removed_sources(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    first = root / "first.txt"
    first.write_text("first", encoding="utf-8")
    removed = root / "removed.txt"
    removed.write_text("old", encoding="utf-8")
    pack = AICoursePreparer().prepare(root)

    first.write_text("changed", encoding="utf-8")
    removed.unlink()
    (root / "new.txt").write_text("new", encoding="utf-8")
    plan = plan_refresh(pack, root)

    assert plan.state == "dirty"
    assert plan.changed_sources == ("first.txt",)
    assert plan.new_sources == ("new.txt",)
    assert plan.removed_sources == ("removed.txt",)


def test_dirty_refresh_reuses_unchanged_derivatives_and_processes_only_new_input(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "kept.txt").write_text("keep this source", encoding="utf-8")
    pack = AICoursePreparer().prepare(root)
    (root / "new.txt").write_text("new source", encoding="utf-8")

    refreshed = AICoursePreparer().prepare(root, existing_pack=pack)

    assert refreshed == pack
    with zipfile.ZipFile(pack) as archive:
        source_manifest = json.loads(archive.read("meta/source_manifest.json"))
        documents = archive.read("meta/documents.jsonl").decode("utf-8")
        assert {item["logical_path"] for item in source_manifest["sources"]} == {"kept.txt", "new.txt"}
        assert "new.txt" in documents
        assert "kept.txt" in documents


def test_removed_source_is_absent_from_refreshed_manifest_and_documents(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "kept.txt").write_text("keep", encoding="utf-8")
    removed = root / "removed.txt"
    removed.write_text("remove", encoding="utf-8")
    pack = AICoursePreparer().prepare(root)
    removed.unlink()

    AICoursePreparer().prepare(root, existing_pack=pack)

    with zipfile.ZipFile(pack) as archive:
        manifest = json.loads(archive.read("meta/source_manifest.json"))
        documents = archive.read("meta/documents.jsonl").decode("utf-8")
        assert {item["logical_path"] for item in manifest["sources"]} == {"kept.txt"}
        assert "removed.txt" not in documents


def test_failed_candidate_never_replaces_valid_pack(tmp_path: Path):
    source_root = tmp_path / "Course"
    source_root.mkdir()
    (source_root / "notes.txt").write_text("source", encoding="utf-8")
    valid = AICoursePreparer().prepare(source_root)
    original = valid.read_bytes()
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"not a zip")

    with pytest.raises(Exception):
        StudyPackRefresher().finalize(
            candidate_pack=invalid,
            final_pack=valid,
            source_root=source_root,
            course_code="CO2013",
            course_name="Course",
            plan=RefreshPlan("dirty", changed_sources=("notes.txt",)),
            exams=[],
        )
    assert valid.read_bytes() == original


def test_unsafe_zip_member_is_rejected_without_replacing_valid_pack(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("source", encoding="utf-8")
    valid = AICoursePreparer().prepare(root)
    original = valid.read_bytes()
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../evil.txt", "nope")
    with pytest.raises(ValueError, match="escapes"):
        StudyPackRefresher().finalize(candidate_pack=unsafe, final_pack=valid, source_root=root, course_code="CO2013", course_name="Course", plan=RefreshPlan("dirty"), exams=[])
    assert valid.read_bytes() == original


def test_v12_manifestless_pack_is_adopted_and_rebuilt_in_place(tmp_path: Path):
    source_root = tmp_path / "Course"
    source_root.mkdir()
    (source_root / "notes.txt").write_text("source", encoding="utf-8")
    pack = AICoursePreparer().prepare(source_root)
    legacy_temp = tmp_path / "legacy.zip"
    with zipfile.ZipFile(pack) as source, zipfile.ZipFile(legacy_temp, "w") as target:
        for name in source.namelist():
            if name in {"meta/pack_manifest.json", "meta/source_manifest.json", "meta/exam_manifest.json"}:
                continue
            target.writestr(name, source.read(name))
    os.replace(legacy_temp, pack)

    refreshed = AICoursePreparer().prepare(source_root)

    assert refreshed == pack
    assert len(list(tmp_path.glob("*_AI_Study_Pack*.zip"))) == 1
    with zipfile.ZipFile(pack) as archive:
        assert "meta/pack_manifest.json" in archive.namelist()


def test_exam_assets_are_indexed_without_absolute_cache_paths(tmp_path: Path):
    from bklms_downloader.coursewave import CourseMatch

    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("source", encoding="utf-8")
    candidate = AICoursePreparer().prepare(root)
    exam_file = tmp_path / "cached-final.pdf"
    exam_file.write_bytes(b"synthetic exam")
    final = tmp_path / "refreshed.zip"
    StudyPackRefresher().finalize(
        candidate_pack=candidate,
        final_pack=final,
        source_root=root,
        course_code="CO2013",
        course_name="Course",
        plan=RefreshPlan("dirty", new_sources=("notes.txt",)),
        exams=[ExamAsset("final-1", "Final 2024.pdf", "final", "2024", "abc", str(exam_file), "https://drive.google.com/file/d/final")],
        enrichment=EnrichmentResult(
            warnings=["Drive folder listing unavailable"],
            match=CourseMatch("matched", "high", "exact code"),
            stage="completed",
            material_link_count=2,
            drive_source_count=1,
            drive_candidate_count=1,
        ),
    )
    with zipfile.ZipFile(final) as archive:
        index = archive.read("06_EXAM_INDEX.md").decode("utf-8")
        manifest = archive.read("meta/exam_manifest.json").decode("utf-8")
        pack_manifest = json.loads(archive.read("meta/pack_manifest.json"))
        exam_manifest = json.loads(manifest)
        protocol = archive.read("02_TUTOR_PROTOCOL.md").decode("utf-8").lower()
        assert "past_exam" in index
        assert str(tmp_path) not in manifest
        assert any(name.startswith("sources/past_exams/") for name in archive.namelist())
        assert "historical exam evidence" in protocol
        assert "guaranteed" in protocol
        assert exam_manifest["diagnostics"]["stage"] == "completed"
        assert exam_manifest["diagnostics"]["drive_source_count"] == 1
        assert pack_manifest["coursewave"]["stage"] == "completed"


def test_local_only_refresh_preserves_existing_exam_assets(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("source", encoding="utf-8")
    candidate = AICoursePreparer().prepare(root)
    exam = tmp_path / "old-final.pdf"
    exam.write_bytes(b"old exam")
    pack = tmp_path / "with-exam.zip"
    refresher = StudyPackRefresher()
    refresher.finalize(candidate_pack=candidate, final_pack=pack, source_root=root, course_code="CO2013", course_name="Course", plan=RefreshPlan("dirty"), exams=[ExamAsset("old", "Old Final.pdf", "final", "2022", "hash", str(exam), "https://drive.google.com/file/d/old")])
    preserved = tmp_path / "preserved.zip"
    refresher.finalize(candidate_pack=pack, final_pack=preserved, source_root=root, course_code="CO2013", course_name="Course", plan=RefreshPlan("dirty"), exams=None)
    with zipfile.ZipFile(preserved) as archive:
        assert "sources/past_exams/old__Old Final.pdf" in archive.namelist()
        assert json.loads(archive.read("meta/exam_manifest.json"))["exams"][0]["stable_id"] == "old"


def test_transient_coursewave_failure_preserves_known_good_exam_set(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("changed local source", encoding="utf-8")
    candidate = AICoursePreparer().prepare(root)
    cached = tmp_path / "old.pdf"
    cached.write_bytes(b"old")
    refresher = StudyPackRefresher()
    prior = tmp_path / "prior.zip"
    refresher.finalize(candidate_pack=candidate, final_pack=prior, source_root=root, course_code="CO2013", course_name="Course", plan=RefreshPlan("dirty"), exams=[ExamAsset("old", "Old Final.pdf", "final", "2022", "hash", str(cached), "https://drive.google.com/file/d/old")])
    refreshed = tmp_path / "refreshed.zip"
    failure = EnrichmentResult(warnings=["Coursewave timeout"], stage="timeout", authoritative=False)
    refresher.finalize(candidate_pack=prior, final_pack=refreshed, source_root=root, course_code="CO2013", course_name="Course", plan=RefreshPlan("dirty", changed_sources=("notes.txt",)), exams=None, enrichment=failure)
    with zipfile.ZipFile(refreshed) as archive:
        assert "sources/past_exams/old__Old Final.pdf" in archive.namelist()
        assert json.loads(archive.read("meta/exam_manifest.json"))["exams"][0]["stable_id"] == "old"
        assert "Old Final.pdf" in archive.read("06_EXAM_INDEX.md").decode("utf-8")
        assert "Coursewave timeout" in archive.read("meta/pack_manifest.json").decode("utf-8")


def test_coursewave_failure_is_optional_for_local_pack(tmp_path: Path):
    root = tmp_path / "Course"
    root.mkdir()
    (root / "notes.txt").write_text("local source", encoding="utf-8")

    class UnavailableEnricher:
        def enrich(self, **_kwargs):
            return EnrichmentResult(warnings=["Coursewave không khả dụng"])

    pack = AICoursePreparer().prepare(
        root,
        course_code="CO2013",
        enrich_exams=True,
        coursewave_enricher=UnavailableEnricher(),
    )

    assert pack.is_file()
    with zipfile.ZipFile(pack) as archive:
        assert "06_EXAM_INDEX.md" in archive.namelist()


def test_coursewave_catalog_failure_is_precise_and_nonfatal():
    from bklms_downloader.coursewave import CoursewaveCatalogResult

    class BrokenCatalog:
        def fetch_catalog_result(self):
            return CoursewaveCatalogResult(
                "catalog_parse_failed",
                warnings=("Không thể phân tích danh mục HCMUT Coursewave.",),
            )

    result = CoursewaveEnricher(catalog_client=BrokenCatalog()).enrich(
        course_code="CO2013", course_name="Hệ cơ sở Dữ liệu"
    )

    assert result.match is not None
    assert result.match.status == "catalog_parse_failed"
    assert result.stage == "catalog_parse_failed"
    assert all("Không tìm thấy môn" not in warning for warning in result.warnings)
