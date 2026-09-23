"""Isolated, unauthenticated Selenium enumeration for public Google Drive folders."""

from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.selenium_manager import SeleniumManager


BROWSER_TIMEOUT_SECONDS = 18.0
BROWSER_POLL_SECONDS = 0.2
BROWSER_IDLE_SCROLL_ROUNDS = 3


def _drive_id(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"/(?:file|document|spreadsheets|presentation)/d/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    match = re.search(r"/folders/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    return parse_qs(parsed.query).get("id", [""])[0]


def _canonical_url(identifier: str, *, is_folder: bool, kind: str = "") -> str:
    if is_folder:
        return f"https://drive.google.com/drive/folders/{identifier}"
    if "spreadsheet" in kind:
        return f"https://docs.google.com/spreadsheets/d/{identifier}/edit"
    if "presentation" in kind or "slide" in kind:
        return f"https://docs.google.com/presentation/d/{identifier}/edit"
    if "document" in kind or "google doc" in kind:
        return f"https://docs.google.com/document/d/{identifier}/edit"
    return f"https://drive.google.com/file/d/{identifier}/view"


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"\s*[,\-–]\s*(?:folder|thư mục|google docs?|google sheets?|google slides?)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:shortcut to )?shared folder\s*$", "", value, flags=re.I)
    value = re.sub(r"(\.(?:pdf|png|jpe?g|txt|docx|pptx))\s+(?:pdf|image|shared file|download)\s*$", r"\1", value, flags=re.I)
    return value.strip()


@dataclass(frozen=True)
class PublicDriveEntry:
    stable_id: str
    name: str
    url: str
    is_folder: bool


@dataclass
class BrowserEnumeration:
    state: str
    items: list[PublicDriveEntry] = field(default_factory=list)
    mode: str = "headless"
    warning: str = ""


def extract_public_drive_entries(html: str) -> list[PublicDriveEntry]:
    """Extract visible Drive rows using stable IDs and accessibility metadata.

    This deliberately accepts several semantic signals instead of generated
    Google CSS class names. It is pure so fixtures can cover UI variations.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: dict[str, PublicDriveEntry] = {}
    candidates = list(soup.find_all("a", href=True)) + list(
        soup.select("[data-id], [data-item-id], [data-file-id], [data-drive-id]")
    )
    for element in candidates:
        anchor = element if element.name == "a" else element.find("a", href=True)
        href = anchor.get("href", "") if anchor else ""
        identifier = _drive_id(href)
        for attribute in ("data-id", "data-item-id", "data-file-id", "data-drive-id"):
            identifier = identifier or str(element.get(attribute, "")).strip()
        # Drive IDs are long; rejecting tiny synthetic/internal values avoids
        # accidental matches from bootstrap markup such as data-id="_gd".
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,}", identifier or ""):
            continue
        semantic_nodes = [element, *element.find_all(attrs={"data-tooltip": True}), *element.find_all(attrs={"aria-label": True})]
        signals = " ".join(
            str(node.get(attribute, ""))
            for node in semantic_nodes
            for attribute in ("aria-label", "title", "data-tooltip", "data-mime-type", "role")
        )
        text = anchor.get_text(" ", strip=True) if anchor else element.get_text(" ", strip=True)
        semantic_name = next(
            (
                str(node.get(attribute, ""))
                for node in semantic_nodes
                for attribute in ("aria-label", "data-tooltip", "title")
                if str(node.get(attribute, "")).strip()
            ),
            "",
        )
        name = _clean_name(semantic_name or text)
        if not name:
            continue
        lower_signals = f"{signals} {name}".casefold()
        is_folder = "/folders/" in href or "folder" in lower_signals or "thư mục" in lower_signals
        url = href if _drive_id(href) else _canonical_url(identifier, is_folder=is_folder, kind=lower_signals)
        candidate = PublicDriveEntry(identifier, name, url, is_folder)
        current = entries.get(identifier)
        if current is None or (candidate.is_folder and not current.is_folder):
            entries[identifier] = candidate
    return list(entries.values())


def _looks_permission_denied(html: str) -> bool:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).casefold()
    return any(token in text for token in (
        "request access", "you need access", "access denied",
        "yêu cầu quyền truy cập", "cần quyền truy cập",
    ))


def create_isolated_public_drive_driver(profile_dir: Path, headless: bool) -> webdriver.Chrome:
    """Create an ephemeral Chrome, never using the app's LMS driver or profile."""
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--incognito")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-US")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,1000")
    service = Service()
    if not service.path:
        paths = SeleniumManager().binary_paths(["--browser", "chrome", "--avoid-stats"])
        if not Path(paths["driver_path"]).is_file() or not Path(paths["browser_path"]).is_file():
            raise RuntimeError("Selenium Manager did not return installed browser/driver files")
        service.path = paths["driver_path"]
        options.binary_location = paths["browser_path"]
    driver = webdriver.Chrome(options=options, service=service)
    driver.set_page_load_timeout(BROWSER_TIMEOUT_SECONDS)
    return driver


DriverFactory = Callable[[Path], webdriver.Chrome]


class PublicDriveBrowserEnumerator:
    """Read only rendered public Drive rows in a disposable browser context."""

    def __init__(
        self,
        *,
        timeout_seconds: float = BROWSER_TIMEOUT_SECONDS,
        max_idle_rounds: int = BROWSER_IDLE_SCROLL_ROUNDS,
        driver_factory: Callable[[Path, bool], webdriver.Chrome] = create_isolated_public_drive_driver,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_idle_rounds = max_idle_rounds
        self.driver_factory = driver_factory

    def enumerate(self, url: str, *, max_items: int, cancel_event: Event | None = None, progress_callback: Callable[[str], None] | None = None) -> BrowserEnumeration:
        self._notify(progress_callback, "Đang kiểm tra thư mục Drive công khai bằng Chrome tạm...")
        result = self._enumerate_once(url, max_items=max_items, cancel_event=cancel_event, headless=True)
        # A rendering failure can be headless-specific. Retry visibly only in
        # that case, still with an isolated anonymous profile and auto-close.
        if result.state == "browser_render_failed":
            self._notify(progress_callback, "Đang thử lại thư mục Drive bằng cửa sổ Chrome tạm...")
            return self._enumerate_once(url, max_items=max_items, cancel_event=cancel_event, headless=False)
        return result

    @staticmethod
    def _notify(callback: Callable[[str], None] | None, message: str) -> None:
        if callback is not None:
            try:
                callback(message)
            except Exception:
                pass

    def _enumerate_once(self, url: str, *, max_items: int, cancel_event: Event | None, headless: bool) -> BrowserEnumeration:
        mode = "headless" if headless else "visible"
        if cancel_event is not None and cancel_event.is_set():
            return BrowserEnumeration("cancelled", mode=mode, warning="Đã hủy kiểm tra thư mục Drive công khai.")
        with tempfile.TemporaryDirectory(prefix="bklms_public_drive_") as temporary:
            driver = None
            try:
                driver = self.driver_factory(Path(temporary), headless)
                driver.get(url)
                deadline = time.monotonic() + self.timeout_seconds
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        return BrowserEnumeration("cancelled", mode=mode, warning="Đã hủy kiểm tra thư mục Drive công khai.")
                    html = driver.page_source
                    if extract_public_drive_entries(html) or _looks_permission_denied(html) or self._ready(driver):
                        break
                    time.sleep(BROWSER_POLL_SECONDS)
                else:
                    return BrowserEnumeration("timeout", mode=mode, warning="Quá thời gian chờ hiển thị thư mục Drive công khai.")
                if _looks_permission_denied(driver.page_source):
                    return BrowserEnumeration("permission_denied", mode=mode, warning="Không có quyền truy cập thư mục Google Drive công khai.")
                items = self._collect_lazy_items(driver, deadline, max_items=max_items, cancel_event=cancel_event)
                if items is None:
                    return BrowserEnumeration("cancelled", mode=mode, warning="Đã hủy kiểm tra thư mục Drive công khai.")
                return BrowserEnumeration("public_enumerated" if items else "public_empty", items, mode=mode)
            except TimeoutException:
                return BrowserEnumeration("timeout", mode=mode, warning="Quá thời gian chờ hiển thị thư mục Drive công khai.")
            except (WebDriverException, OSError, RuntimeError) as exc:
                return BrowserEnumeration("browser_render_failed", mode=mode, warning=f"Không thể hiển thị thư mục Drive công khai: {type(exc).__name__}.")
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass

    @staticmethod
    def _ready(driver) -> bool:
        try:
            return driver.execute_script("return document.readyState") in ("interactive", "complete")
        except Exception:
            return False

    def _collect_lazy_items(self, driver, deadline: float, *, max_items: int, cancel_event: Event | None) -> list[PublicDriveEntry] | None:
        seen: dict[str, PublicDriveEntry] = {}
        idle_rounds = 0
        while time.monotonic() < deadline and idle_rounds < self.max_idle_rounds and len(seen) < max_items:
            if cancel_event is not None and cancel_event.is_set():
                return None
            before = len(seen)
            for item in extract_public_drive_entries(driver.page_source):
                if len(seen) >= max_items:
                    break
                seen.setdefault(item.stable_id, item)
            if len(seen) == before:
                idle_rounds += 1
            else:
                idle_rounds = 0
            try:
                driver.execute_script(
                    "const nodes=[...document.querySelectorAll('[role=main],[role=grid],[role=list]')];"
                    "const target=nodes.sort((a,b)=>(b.scrollHeight-b.clientHeight)-(a.scrollHeight-a.clientHeight))[0];"
                    "if(target && target.scrollHeight>target.clientHeight){target.scrollTop+=target.clientHeight||600;}"
                    "else {window.scrollBy(0, Math.max(window.innerHeight, 600));}"
                )
            except Exception:
                break
            poll_until = min(deadline, time.monotonic() + 1.0)
            while time.monotonic() < poll_until:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                if len(extract_public_drive_entries(driver.page_source)) > len(seen):
                    break
                time.sleep(BROWSER_POLL_SECONDS)
        return list(seen.values())
