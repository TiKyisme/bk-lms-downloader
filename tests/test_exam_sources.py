from pathlib import Path
from threading import Event
from types import SimpleNamespace

from bklms_downloader.exam_sources import (
    DriveItem,
    ExamCandidate,
    ExamCache,
    GoogleDriveProvider,
    classify_exam,
    is_exam_context,
)


def response(*, text="", content=b"", status=200, headers=None):
    return SimpleNamespace(
        text=text,
        status_code=status,
        headers=headers or {},
        raise_for_status=lambda: None if status < 400 else (_ for _ in ()).throw(Exception("status")),
        iter_content=lambda _size: [content],
        close=lambda: None,
    )


def test_exam_classification_is_conservative():
    for label in ("Đề thi", "de thi", "Đề thi các năm", "exam", "past exam", "Giữa kỳ", "giua ki", "GK", "Final", "cuối kì", "CK"):
        assert is_exam_context(label)
    assert classify_exam("Mid-term HK231.pdf") == "midterm"
    assert classify_exam("Đề cuối kỳ 2024.pdf") == "final"
    assert classify_exam("Bài tập.pdf", in_exam_context=False) is None
    assert classify_exam("Đề năm trước.pdf", in_exam_context=True) == "unknown_exam"


def test_public_folder_discovery_keeps_midterm_final_and_ignores_unrelated():
    folder = "https://drive.google.com/drive/folders/root"
    html = """
      <a href="https://drive.google.com/file/d/mid/view">Midterm 2023.pdf</a>
      <a href="https://drive.google.com/file/d/final/view">Final HK231.pdf</a>
      <a href="https://drive.google.com/file/d/lab/view">Lab sheet.pdf</a>
    """

    class Session:
        def get(self, _url, **_kwargs):
            return response(text=html)

    discovered = GoogleDriveProvider(Session()).discover([folder])
    assert {item.exam_type for item in discovered.candidates} == {"midterm", "final"}
    assert len(discovered.candidates) == 2


def test_direct_public_exam_link_uses_supplied_material_label():
    provider = GoogleDriveProvider(SimpleNamespace())
    discovered = provider.discover(
        [DriveItem("https://drive.google.com/file/d/final/view", "Final 2024.pdf")]
    )

    assert [item.exam_type for item in discovered.candidates] == ["final"]


def test_download_cache_reuses_valid_payload_and_rejects_corruption(tmp_path: Path):
    cache = ExamCache(tmp_path / "cache")
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"synthetic exam")
    cached = cache.put("drive-id", source, etag="etag")

    assert cache.get("drive-id") is not None
    Path(cached.path).write_bytes(b"corrupted")
    assert cache.get("drive-id") is None


def test_cancelled_download_cleans_partial_file(tmp_path: Path):
    class Session:
        def get(self, _url, **_kwargs):
            return response(content=b"payload")

    cancel = Event()
    cancel.set()
    candidate = ExamCandidate("exam", "https://drive.google.com/file/d/exam/view", "Final.pdf", "final")
    output, _etag, _modified, warning = GoogleDriveProvider(Session()).download(candidate, tmp_path, cancel_event=cancel)

    assert output is None
    assert "hủy" in warning.lower()
    assert list(tmp_path.glob("*.part")) == []
