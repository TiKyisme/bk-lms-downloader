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
    infer_term,
)
from bklms_downloader.public_drive_browser import BrowserEnumeration, PublicDriveEntry
from bklms_downloader.url_security import is_public_drive_url


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
    assert classify_exam("CK.pdf") == "final"
    assert classify_exam("Đề CK 2024.pdf") == "final"
    assert classify_exam("GK HK221.pdf") == "midterm"
    assert classify_exam("GK.pdf") == "midterm"
    assert classify_exam("Đề GK 2024.pdf") == "midterm"
    assert classify_exam("CK HK221.pdf") == "final"
    for name in ("Examples.pdf", "Example code.pdf", "Checklist.pdf", "Backpropagation.pdf", "Packet.pdf"):
        assert classify_exam(name) is None
    assert classify_exam("THI CK") == "final"
    assert classify_exam("THI GK") == "midterm"
    assert infer_term("Final_201_with_keys.pdf", in_exam_context=True) == "201"
    assert infer_term("Midterm_221_with_keys.pdf", in_exam_context=True) == "221"
    assert infer_term("On_tap_CK_202.pdf", in_exam_context=True) == "202"


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


def test_exam_cache_stale_or_changed_same_id_is_not_reused_forever(tmp_path: Path):
    cache = ExamCache(tmp_path / "cache")
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"first")
    first = cache.put("same-id", source)
    source.write_bytes(b"changed")
    updated = cache.put("same-id", source)
    assert updated.sha256 != first.sha256
    assert Path(cache.get("same-id").path).read_bytes() == b"changed"
    index = __import__("json").loads(cache.index_path.read_text(encoding="utf-8"))
    index["same-id"]["cached_at"] = 0
    cache.index_path.write_text(__import__("json").dumps(index), encoding="utf-8")
    assert cache.get("same-id") is None


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


def test_deep_exam_context_propagates_type_term_and_official_variant(tmp_path: Path):
    root = "https://drive.google.com/drive/folders/root"
    mapping = {
        root: [PublicDriveEntry("exam-root", "Đề thi", "https://drive.google.com/drive/folders/exam-root", True)],
        "https://drive.google.com/drive/folders/exam-root": [PublicDriveEntry("ck", "THI CK", "https://drive.google.com/drive/folders/ck", True)],
        "https://drive.google.com/drive/folders/ck": [PublicDriveEntry("term201", "201", "https://drive.google.com/drive/folders/term201", True)],
        "https://drive.google.com/drive/folders/term201": [PublicDriveEntry("official", "CHÍNH THỨC", "https://drive.google.com/drive/folders/official", True)],
        "https://drive.google.com/drive/folders/official": [PublicDriveEntry("paper", "paper.pdf", "https://drive.google.com/file/d/paper/view", False)],
    }
    class Browser:
        def enumerate(self, url, **_kwargs): return BrowserEnumeration("public_enumerated", mapping.get(url, []))
    class Session:
        def get(self, _url, **_kwargs): return response(text="<html></html>")
    discovered = GoogleDriveProvider(Session(), max_depth=8, metadata_cache=__import__("bklms_downloader.exam_sources", fromlist=["DriveMetadataCache"]).DriveMetadataCache(tmp_path), browser_enumerator=Browser()).discover([root])
    assert [(item.exam_type, item.term, item.exam_variant) for item in discovered.candidates] == [("final", "201", "official")]


def test_year_outside_exam_context_is_not_crawled_or_classified(tmp_path: Path):
    root = "https://drive.google.com/drive/folders/root"
    class Browser:
        def enumerate(self, url, **_kwargs):
            return BrowserEnumeration("public_enumerated", [PublicDriveEntry("year2024", "2024", "https://drive.google.com/drive/folders/year2024", True)] if url == root else [PublicDriveEntry("lecture", "lecture.pdf", "https://drive.google.com/file/d/lecture/view", False)])
    class Session:
        def get(self, _url, **_kwargs): return response(text="<html></html>")
    discovered = GoogleDriveProvider(Session(), metadata_cache=__import__("bklms_downloader.exam_sources", fromlist=["DriveMetadataCache"]).DriveMetadataCache(tmp_path), browser_enumerator=Browser()).discover([root])
    assert discovered.candidates == []
    assert discovered.state_counts["skipped_non_exam_folder"] == 1


def test_malicious_google_lookalikes_are_not_public_drive_sources():
    for url in ("https://evilgoogle.com/file/d/x", "https://drive.google.com.attacker.example/file/d/x", "https://docs.google.com.evil.example/document/d/x"):
        assert not is_public_drive_url(url)


def test_high_priority_timeout_retries_once_and_does_not_block_sibling(tmp_path: Path):
    root = "https://drive.google.com/drive/folders/root"
    ck = "https://drive.google.com/drive/folders/ckbranch"
    gk = "https://drive.google.com/drive/folders/gkbranch"
    class Browser:
        def __init__(self): self.calls = {}
        def enumerate(self, url, **_kwargs):
            self.calls[url] = self.calls.get(url, 0) + 1
            if url == root: return BrowserEnumeration("public_enumerated", [PublicDriveEntry("ckbranch", "THI CK", ck, True), PublicDriveEntry("gkbranch", "THI GK", gk, True)])
            if url == ck and self.calls[url] == 1: return BrowserEnumeration("timeout")
            suffix = "ck" if url == ck else "gk"
            return BrowserEnumeration("public_enumerated", [PublicDriveEntry("paper" + suffix, "paper.pdf", "https://drive.google.com/file/d/paper" + suffix + "/view", False)])
    class Session:
        def get(self, _url, **_kwargs): return response(text="<html></html>")
    browser = Browser()
    found = GoogleDriveProvider(Session(), metadata_cache=__import__("bklms_downloader.exam_sources", fromlist=["DriveMetadataCache"]).DriveMetadataCache(tmp_path), browser_enumerator=browser).discover([root])
    assert browser.calls[ck] == 2
    assert browser.calls[gk] == 1
    assert {item.exam_type for item in found.candidates} == {"final", "midterm"}
