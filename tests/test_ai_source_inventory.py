from pathlib import Path

from bklms_downloader.ai_sources import inventory_course_sources, safe_relative_diagnostic_path


def test_inventory_counts_office_material_and_downloader_metadata_without_absolute_paths(tmp_path: Path):
    for name in (
        "lecture.pdf",
        "slides.pptx",
        "notes.docx",
        "data.xlsx",
        "macro.xlsm",
        "table.csv",
        "readme.txt",
        "unknown.bin",
    ):
        (tmp_path / name).write_bytes(b"synthetic source")
    metadata = tmp_path / "_meta" / "course_structure.json"
    metadata.parent.mkdir()
    metadata.write_text("{}", encoding="utf-8")
    generated = tmp_path / "AI_Knowledge"
    generated.mkdir()
    (generated / "old_chunk.txt").write_text("not an input", encoding="utf-8")
    (tmp_path / "Sample_AI_Study_Pack.zip").write_bytes(b"not an input")

    inventory = inventory_course_sources(tmp_path)

    assert inventory.total_source_files == 9
    assert inventory.extension_counts[".docx"] == 1
    assert inventory.extension_counts[".xlsx"] == 1
    assert inventory.extension_counts[".xlsm"] == 1
    assert inventory.extension_counts[".csv"] == 1
    assert inventory.supported_files == 7
    assert inventory.unsupported_files == 1
    assert inventory.lecturer_material_candidates == 7
    assert inventory.downloader_metadata_files == 1
    assert inventory.unsupported_relative_paths == ("unknown.bin",)
    assert str(tmp_path) not in repr(inventory.to_dict())


def test_inventory_reports_empty_course_and_does_not_treat_zip_as_teaching_input(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert inventory_course_sources(empty).total_source_files == 0

    (empty / "nested_archive.zip").write_bytes(b"arbitrary zip")
    inventory = inventory_course_sources(empty)
    assert inventory.unsupported_files == 1
    assert inventory.unsupported_relative_paths == ("nested_archive.zip",)


def test_relative_diagnostic_filenames_redact_credential_like_values():
    safe = safe_relative_diagnostic_path("attachments/sessionid=private-value.bin")

    assert safe == "attachments/sessionid=[redacted]"
    assert "private-value" not in safe
