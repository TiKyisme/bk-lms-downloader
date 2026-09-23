from types import SimpleNamespace

from bklms_downloader.coursewave import (
    CoursewaveCatalogCache,
    CoursewaveClient,
    CoursewaveCourse,
    discover_published_tabs,
    match_course,
    parse_coursewave_table,
)


TABLE = """
<table>
  <tr><th>Mã môn</th><th>Tên môn</th><th>Giảng viên</th><th>Tài liệu</th></tr>
  <tr><td>CO 2013</td><td>Hệ cơ sở dữ liệu</td><td>GV A</td><td><a href="https://drive.google.com/file/d/one/view">Đề giữa kỳ</a></td></tr>
  <tr><td></td><td></td><td>GV B</td><td><a href="https://drive.google.com/file/d/two/view">Đề cuối kỳ</a></td></tr>
</table>
"""


def test_coursewave_table_inherits_merged_cells_and_keeps_all_links():
    courses = parse_coursewave_table(TABLE, category="Khoa CNTT", base_url="https://example.test/catalog")

    assert [course.course_code for course in courses] == ["CO2013", "CO2013"]
    assert courses[1].course_name == "Hệ cơ sở dữ liệu"
    assert {link.url for course in courses for link in course.material_links} == {
        "https://drive.google.com/file/d/one/view",
        "https://drive.google.com/file/d/two/view",
    }


def test_exact_code_wins_and_name_ambiguity_never_auto_matches():
    courses = parse_coursewave_table(TABLE, category="Khoa CNTT", base_url="https://example.test/catalog")
    exact = match_course(course_code=" co-2013 ", course_name="Tên khác", courses=courses)
    assert exact.status == "matched"
    assert exact.confidence == "high"
    assert len(exact.candidates[0].material_links) == 2

    ambiguous = match_course(
        course_code="",
        course_name="Lập trình",
        courses=[
            CoursewaveCourse("CO1001", "Lập trình", "A", "A", []),
            CoursewaveCourse("CO1002", "Lập trình", "B", "B", []),
        ],
    )
    assert ambiguous.status == "ambiguous"
    assert ambiguous.confidence == "low"


def test_tab_discovery_and_client_fetch_all_published_tabs(tmp_path):
    root = '<a href="#gid=1">Khoa A</a><a href="?gid=2#gid=2">Khoa B</a>'
    tabs = discover_published_tabs(root, base_url="https://example.test/pubhtml")
    assert len(tabs) == 2

    class Session:
        def get(self, url, **_kwargs):
            html = root if "pubhtml" in url and "gid=" not in url else TABLE
            return SimpleNamespace(text=html, status_code=200, url=url, raise_for_status=lambda: None, close=lambda: None)

    catalog = CoursewaveClient(Session(), cache=CoursewaveCatalogCache(path=tmp_path / "catalog.json")).fetch_catalog("https://example.test/pubhtml")
    assert len(catalog) >= 2


def test_non_default_sheet_rowspan_and_short_vietnamese_headers_match_co2013(tmp_path):
    root = '''
    <script>
      items.push({name: "DEFAULT", pageUrl: "https://example.test/pubhtml/sheet?gid=1", gid: "1"});
      items.push({name: "C\u01a0 S\u1ede", pageUrl: "https://example.test/pubhtml/sheet?gid=2", gid: "2"});
    </script>
    '''
    other = "<table><tr><th>Mã</th><th>Tên môn học</th><th>Tài liệu</th></tr><tr><td>CO1001</td><td>Khác</td><td></td></tr></table>"
    course = '''
    <table>
      <tr><th></th><th>Mã</th><th>Tên môn học</th><th>Giảng viên</th><th>Video</th><th>Tài liệu</th><th>Ghi chú</th></tr>
      <tr><th>1</th><td rowspan="3">CO2013</td><td rowspan="3">Hệ cơ sở Dữ liệu</td><td>Lecturer A</td><td><a href="https://youtube.test/a">Video</a></td><td><a href="https://www.google.com/url?q=https%3A%2F%2Fdrive.google.com%2Fdrive%2Fu%2F1%2Ffolders%2Ffolder-one">Materials A</a></td><td></td></tr>
      <tr><th>2</th><td>Lecturer B</td><td></td><td><a href="https://drive.google.com/drive/folders/folder-two">Materials B</a></td><td></td></tr>
      <tr><th>3</th><td>Lecturer B</td><td></td><td><a href="https://drive.google.com/drive/folders/folder-two">Duplicate</a></td><td></td></tr>
      <tr><th>4</th><td>CO3001</td><td>Unrelated</td><td>Other</td><td></td><td><a href="https://drive.google.com/drive/folders/other">Other</a></td><td></td></tr>
    </table>
    '''

    class Session:
        def get(self, url, **_kwargs):
            html = root if url.endswith("pubhtml") else (course if "gid=2" in url else other)
            return SimpleNamespace(text=html, status_code=200, url=url, raise_for_status=lambda: None, close=lambda: None)

    result = CoursewaveClient(Session(), cache=CoursewaveCatalogCache(path=tmp_path / "catalog.json")).fetch_catalog_result("https://example.test/pubhtml")
    match = match_course(course_code="CO2013", course_name="Wrong name", courses=result.courses)

    assert result.status == "ok"
    assert [tab.gid for tab in result.tabs] == ["1", "2"]
    assert match.status == "matched"
    assert match.confidence == "high"
    assert match.candidates[0].course_code == "CO2013"
    assert match.candidates[0].categories == ("CƠ SỞ",)
    assert set(match.candidates[0].lecturers) == {"Lecturer A", "Lecturer B"}
    assert {link.url for link in match.candidates[0].material_links} == {
        "https://drive.google.com/drive/u/1/folders/folder-one",
        "https://drive.google.com/drive/folders/folder-two",
        "https://youtube.test/a",
    }


def test_catalog_fetch_failure_is_not_reported_as_no_match(tmp_path):
    import requests

    class Session:
        def get(self, _url, **_kwargs):
            raise requests.ConnectionError("offline")

    result = CoursewaveClient(Session(), cache=CoursewaveCatalogCache(path=tmp_path / "catalog.json")).fetch_catalog_result("https://example.test/pubhtml", force_refresh=True)

    assert result.status == "fetch_failed"
    assert result.status != "no_match"
