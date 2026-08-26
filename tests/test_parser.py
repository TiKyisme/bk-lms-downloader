from pathlib import Path

from bklms_downloader.parser import extract_section_content, parse_sections


FIXTURE = Path(__file__).parent / "fixtures" / "course_sample.html"


def test_parse_sections_and_order():
    html = FIXTURE.read_text(encoding="utf-8")
    name, sections = parse_sections(html, "https://lms.hcmut.edu.vn/course/view.php?id=123456")

    assert name == "Mạng máy tính (CO3093)"
    assert len(sections) == 2
    assert sections[0].title == "Chung"
    assert sections[1].title == "Chapter 1 - Introduction"

    assert sections[1].activities[0].order == 1
    assert sections[1].activities[0].name == "Chapter 1 v9.0"
    assert sections[1].activities[0].mod_type == "resource"
    assert sections[1].activities[1].mod_type == "quiz"


def test_extract_inline_content_removes_activity_cards():
    html = FIXTURE.read_text(encoding="utf-8")
    _, sections = parse_sections(html, "https://lms.hcmut.edu.vn/course/view.php?id=123456")
    html_doc, media, links = extract_section_content(
        sections[1].node_html,
        "https://lms.hcmut.edu.vn/course/view.php?id=123456",
    )
    assert html_doc is not None
    assert "Network edge and network core" in html_doc
    assert "Chapter 1 v9.0" not in html_doc
    assert media == []
