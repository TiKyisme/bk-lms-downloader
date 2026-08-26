from pathlib import Path

from bklms_downloader.crawler import DeepDownloader
from bklms_downloader.models import Activity, Section


class FakeResponse:
    def __init__(self, url, content=b"", content_type="text/html", filename=None):
        self.url = url
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.encoding = "utf-8"
        self.headers = {"Content-Type": content_type}
        if filename:
            self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        return None


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, **kwargs):
        return self.mapping[url]


def test_linked_course_is_flattened_into_root_lab_folder(monkeypatch, tmp_path):
    root_url = "https://lms.hcmut.edu.vn/course/view.php?id=1"
    linked_url = "https://lms.hcmut.edu.vn/course/view.php?id=2"
    lab1_url = "https://lms.hcmut.edu.vn/pluginfile.php/1/lab1.pdf"
    lab8_url = "https://lms.hcmut.edu.vn/pluginfile.php/1/lab8.pdf"

    mapping = {
        root_url: FakeResponse(root_url, b"ROOT"),
        linked_url: FakeResponse(linked_url, b"LINKED"),
        lab1_url: FakeResponse(
            lab1_url,
            b"lab1",
            "application/pdf",
            "guide.pdf",
        ),
        lab8_url: FakeResponse(
            lab8_url,
            b"lab8",
            "application/pdf",
            "guide.pdf",
        ),
    }

    def fake_parse_sections(html, base_url):
        if html == "ROOT":
            return (
                "Main Course",
                [
                    Section(
                        0,
                        "Chung",
                        "<section></section>",
                        [Activity(1, "Learning materials", linked_url, "course")],
                    )
                ],
            )
        return (
            "Linked Course",
            [
                Section(
                    1,
                    "Lab 1_ Introduction",
                    "<section></section>",
                    [Activity(1, "Guide", lab1_url, "resource")],
                ),
                Section(
                    2,
                    "Lab 8_ Wireless Network",
                    "<section></section>",
                    [Activity(1, "Guide", lab8_url, "resource")],
                ),
            ],
        )

    monkeypatch.setattr(
        "bklms_downloader.crawler.parse_sections",
        fake_parse_sections,
    )

    downloader = DeepDownloader(
        session=FakeSession(mapping),
        output=tmp_path,
        follow_linked_courses=True,
    )
    course_dir = downloader.crawl_course(root_url, tmp_path)

    assert course_dir == tmp_path / "Main Course"
    lab_dir = course_dir / "03_Lab"
    assert lab_dir.is_dir()

    names = sorted(path.name for path in lab_dir.iterdir())
    assert any(name.startswith("Lab 1_ Introduction - ") for name in names)
    assert any(name.startswith("Lab 8_ Wireless Network - ") for name in names)

    all_dirs = [p.name for p in course_dir.rglob("*") if p.is_dir()]
    assert not any(name.startswith("COURSE_") for name in all_dirs)
    assert "_inline_content" not in all_dirs
    assert "_meta" in all_dirs
