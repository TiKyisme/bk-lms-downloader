import json
import sys
import sys
import zipfile
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from bklms_downloader.ai_prepare import AICoursePreparer
from bklms_downloader.ai_study_pack import NAVIGATION_FILES, validate_ai_study_pack


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from prepare_ai_course import chapter_numbers_from_path, classify_group


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from prepare_ai_course import chapter_numbers_from_path, classify_group


def _write_pdf(path: Path, title: str, *, visual: bool = False) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, 720, title)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 690, "Lecturer terminology and source-backed explanation.")
    if visual:
        pdf.rect(90, 510, 150, 70)
        pdf.rect(360, 510, 150, 70)
        pdf.line(240, 545, 360, 545)
        pdf.drawString(118, 545, "Requirements")
        pdf.drawString(392, 545, "Design")
        pdf.drawString(190, 485, "Diagram: requirements flow into design")
    pdf.showPage()
    pdf.save()


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_full_ai_study_pack_contract_and_zip_round_trip(tmp_path: Path):
    course_root = tmp_path / "Software Engineering (CO3001)"
    course_root.mkdir()
    syllabus = course_root / "Course Syllabus"
    syllabus.mkdir()
    (syllabus / "content.txt").write_text(
        "Course syllabus. Lecturer assessment and learning outcomes.",
        encoding="utf-8",
    )
    _write_pdf(course_root / "Slides - 01_Ch1 Introduction.pdf", "Chapter 1 Introduction")
    chapter_two = course_root / "Slides - 02_Ch2 Software Processes.pdf"
    _write_pdf(chapter_two, "Chapter 2 Software Processes")
    _write_pdf(
        course_root / "Slides - 03_Ch3_4 Requirements Engineering.pdf",
        "Chapters 3 and 4 Requirements Engineering",
        visual=True,
    )
    _write_pdf(course_root / "Slides - 06_Ch6 System Modeling.pdf", "Chapter 6 System Modeling")
    duplicate = course_root / "Duplicate - 02_Ch2 Software Processes.pdf"
    duplicate.write_bytes(chapter_two.read_bytes())
    (course_root / "Teaching Plan.url").write_text(
        "[InternetShortcut]\nURL=https://lms.example.edu/teaching-plan\n",
        encoding="utf-8",
    )

    output = AICoursePreparer().prepare(course_root)
    report = validate_ai_study_pack(output)

    assert report.errors == []
    assert any("Chapter 5" in warning for warning in report.warnings)
    assert all((output / name).is_file() for name in NAVIGATION_FILES)
    assert (output / "chapters" / "chapter_01.md").is_file()
    assert (output / "chapters" / "chapter_02.md").is_file()
    assert (output / "chapters" / "chapter_03_04.md").is_file()
    assert (output / "chapters" / "chapter_06.md").is_file()

    records = _records(output / "meta" / "documents.jsonl")
    ready_lectures = [record for record in records if record["source_type"] == "lecture_pdf" and record["status"] == "ready"]
    assert {tuple(record["chapters"]) for record in ready_lectures} == {(1,), (2,), (3, 4), (6,)}
    assert all(record["group"].startswith("chapter_") for record in ready_lectures)
    assert all(record["source_copy_path"] for record in ready_lectures)
    assert sum(record["status"] == "duplicate" for record in records) == 1
    assert sum(record["status"] == "link_only" for record in records) == 1
    assert all(not Path(record["source_path"]).is_absolute() for record in records)

    chunks = _records(output / "meta" / "corpus.jsonl")
    assert chunks and all(chunk["source_id"] and chunk["locator"] for chunk in chunks)
    assert any(chunk["chapters"] == [3, 4] for chunk in chunks)

    packs = list(course_root.glob("* - AI Study Pack.zip"))
    assert len(packs) == 1
    with zipfile.ZipFile(packs[0]) as archive:
        names = set(archive.namelist())
        assert "START_HERE.md" in names
        assert "COURSE_MAP.md" in names
        assert "COVERAGE_REPORT.md" in names
        assert "CHATGPT_START_PROMPT.txt" in names
        assert any(name.startswith("sources/") for name in names)
        unpacked = tmp_path / "unpacked"
        archive.extractall(unpacked)
    assert validate_ai_study_pack(unpacked).errors == []


def test_chapter_detection_handles_single_numbers_and_explicit_ranges():
    cases = {
        "01_Ch1 Introduction.pdf": ([1], ("chapter_01", 1)),
        "Ch 2 Software Processes.pdf": ([2], ("chapter_02", 2)),
        "Chapter 03 Requirements.pdf": ([3], ("chapter_03", 3)),
        "03_Ch3_4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
        "Chapter 3-4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
        "Ch 3 & 4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
    }

    for filename, (chapters, group) in cases.items():
        path = Path(filename)
        assert chapter_numbers_from_path(path) == chapters
        assert classify_group(path) == group


def test_validator_reports_missing_navigation_as_a_structural_error(tmp_path: Path):
    report = validate_ai_study_pack(tmp_path)

    assert not report.valid
    assert any("Missing navigation file: START_HERE.md" in error for error in report.errors)


def test_chapter_detection_handles_single_numbers_and_explicit_ranges():
    cases = {
        "01_Ch1 Introduction.pdf": ([1], ("chapter_01", 1)),
        "Ch 2 Software Processes.pdf": ([2], ("chapter_02", 2)),
        "Chapter 03 Requirements.pdf": ([3], ("chapter_03", 3)),
        "03_Ch3_4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
        "Chapter 3-4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
        "Ch 3 & 4 Requirements.pdf": ([3, 4], ("chapter_03_04", 3)),
    }

    for filename, (chapters, group) in cases.items():
        path = Path(filename)
        assert chapter_numbers_from_path(path) == chapters
        assert classify_group(path) == group


def test_validator_reports_missing_navigation_as_a_structural_error(tmp_path: Path):
    report = validate_ai_study_pack(tmp_path)

    assert not report.valid
    assert any("Missing navigation file: START_HERE.md" in error for error in report.errors)
