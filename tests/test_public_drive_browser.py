from pathlib import Path
from threading import Event
from types import SimpleNamespace

from bklms_downloader.exam_sources import GoogleDriveProvider
from bklms_downloader.public_drive_browser import (
    BrowserEnumeration,
    PublicDriveBrowserEnumerator,
    PublicDriveEntry,
    extract_public_drive_entries,
)


RENDERED_ROWS = """
<div role="row" data-id="folder-exams" aria-label="Đề thi các năm, Folder"><span>Đề thi các năm</span></div>
<div role="row" data-id="file-final" aria-label="Final HK231.pdf"><a href="https://drive.google.com/file/d/file-final/view">Final HK231.pdf</a></div>
<div role="row" data-id="file-final" aria-label="Final HK231.pdf"><a href="https://drive.google.com/file/d/file-final/view">Final HK231.pdf</a></div>
<div role="row" data-id="doc-midterm" aria-label="Midterm notes, Google Docs">Midterm notes</div>
"""


def test_rendered_drive_dom_extracts_folders_files_docs_and_deduplicates():
    entries = {entry.stable_id: entry for entry in extract_public_drive_entries(RENDERED_ROWS)}

    assert set(entries) == {"folder-exams", "file-final", "doc-midterm"}
    assert entries["folder-exams"].is_folder
    assert entries["file-final"].url.endswith("/file-final/view")
    assert entries["doc-midterm"].url.startswith("https://docs.google.com/document/d/")


class FakeDriver:
    def __init__(self, pages, *, ready=True):
        self.pages = pages
        self.index = 0
        self.ready = ready
        self.get_urls = []
        self.quit_called = False

    @property
    def page_source(self):
        return self.pages[self.index]

    def get(self, url):
        self.get_urls.append(url)

    def execute_script(self, script):
        if "document.readyState" in script:
            return "complete" if self.ready else "loading"
        if self.index + 1 < len(self.pages):
            self.index += 1

    def quit(self):
        self.quit_called = True


def test_browser_enumerator_accumulates_lazy_loaded_rows_and_cleans_driver():
    first = '<div role="row" data-id="item-one" aria-label="Đề thi, Folder">Đề thi</div>'
    second = first + '<div role="row" data-id="item-two" aria-label="Final 2024.pdf">Final 2024.pdf</div>'
    driver = FakeDriver([first, second])
    enumerator = PublicDriveBrowserEnumerator(timeout_seconds=1, max_idle_rounds=2, driver_factory=lambda _profile, _headless: driver)

    result = enumerator.enumerate("https://drive.google.com/drive/folders/root", max_items=20)

    assert result.state == "public_enumerated"
    assert {entry.stable_id for entry in result.items} == {"item-one", "item-two"}
    assert driver.quit_called


def test_browser_enumerator_reports_permission_timeout_cancel_and_render_failure():
    denied = FakeDriver(["<p>You need access</p>"])
    permission = PublicDriveBrowserEnumerator(driver_factory=lambda _profile, _headless: denied).enumerate("https://drive.google.com/drive/folders/root", max_items=5)
    assert permission.state == "permission_denied"

    timeout = PublicDriveBrowserEnumerator(timeout_seconds=0, driver_factory=lambda _profile, _headless: FakeDriver([""], ready=False)).enumerate("https://drive.google.com/drive/folders/root", max_items=5)
    assert timeout.state == "timeout"

    cancelled = Event()
    cancelled.set()
    assert PublicDriveBrowserEnumerator().enumerate("https://drive.google.com/drive/folders/root", max_items=5, cancel_event=cancelled).state == "cancelled"

    failed = PublicDriveBrowserEnumerator(driver_factory=lambda _profile, _headless: (_ for _ in ()).throw(RuntimeError("no browser"))).enumerate("https://drive.google.com/drive/folders/root", max_items=5)
    assert failed.state == "browser_render_failed"
    assert failed.mode == "visible"


def test_provider_uses_browser_fallback_and_recurses_into_exam_folder(tmp_path: Path):
    root = "https://drive.google.com/drive/folders/root"
    exams = "https://drive.google.com/drive/folders/exams"

    class Browser:
        def enumerate(self, url, **_kwargs):
            if url == root:
                return BrowserEnumeration("public_enumerated", [PublicDriveEntry("exams", "Đề thi các năm", exams, True)])
            return BrowserEnumeration("public_enumerated", [PublicDriveEntry("final", "Final HK231.pdf", "https://drive.google.com/file/d/final/view", False)])

    class Session:
        def get(self, _url, **_kwargs):
            return SimpleNamespace(text="<html></html>", status_code=200, raise_for_status=lambda: None, close=lambda: None)

    provider = GoogleDriveProvider(Session(), browser_enumerator=Browser(), metadata_cache=__import__("bklms_downloader.exam_sources", fromlist=["DriveMetadataCache"]).DriveMetadataCache(tmp_path))
    discovery = provider.discover([root])

    assert [candidate.exam_type for candidate in discovery.candidates] == ["final"]
    assert discovery.state_counts["public_enumerated"] == 2
    assert [entry.mode for entry in discovery.folder_results] == ["headless", "headless"]


def test_provider_keeps_browser_public_empty_and_permission_states(tmp_path: Path):
    class Session:
        def get(self, _url, **_kwargs):
            return SimpleNamespace(text="<html></html>", status_code=200, raise_for_status=lambda: None, close=lambda: None)

    class Browser:
        def enumerate(self, _url, **_kwargs):
            return BrowserEnumeration("permission_denied", warning="denied")

    provider = GoogleDriveProvider(Session(), browser_enumerator=Browser(), metadata_cache=__import__("bklms_downloader.exam_sources", fromlist=["DriveMetadataCache"]).DriveMetadataCache(tmp_path))
    discovery = provider.discover(["https://drive.google.com/drive/folders/root"])

    assert discovery.candidates == []
    assert discovery.state_counts == {"permission_denied": 1}
    assert discovery.warnings == ["denied"]
