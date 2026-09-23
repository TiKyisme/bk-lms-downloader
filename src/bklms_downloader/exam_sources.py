"""Public Google Drive exam discovery, bounded downloads, and local cache safety."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .platform_support import user_config_dir
from .public_drive_browser import BrowserEnumeration, PublicDriveBrowserEnumerator
from .url_security import is_public_drive_url
from .utils import safe_name


DRIVE_TIMEOUT = (5, 25)
MAX_EXAM_BYTES = 35 * 1024 * 1024
DRIVE_METADATA_CACHE_SCHEMA_VERSION = 2
EXAM_CACHE_FRESHNESS_SECONDS = 6 * 60 * 60
SUPPORTED_EXAM_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".docx", ".pptx"}
EXAM_FOLDER_HINTS = (
    "de thi", "de cac nam", "exam", "exams", "past exam", "past exams",
    "midterm", "mid term", "giua ky", "giua ki", "gk", "final", "finals", "cuoi ky", "cuoi ki", "ck",
)
GENERIC_PARENT_FOLDER_HINTS = ("tai lieu", "document", "archive", "semester", "year", "nam hoc", "hoc ky", "hk")
MAX_TRAVERSAL_SECONDS = 75.0


def folded(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).strip().casefold()


def drive_id(url: str) -> str:
    if not is_public_drive_url(url):
        return ""
    parsed = urlparse(url)
    match = re.search(r"/(?:file|document|spreadsheets|presentation)/d/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    if "/folders/" in parsed.path:
        match = re.search(r"/folders/([^/?#]+)", parsed.path)
        return match.group(1) if match else ""
    return parse_qs(parsed.query).get("id", [""])[0]


def canonical_drive_url(url: str) -> str:
    if not is_public_drive_url(url):
        return ""
    identifier = drive_id(url)
    parsed = urlparse(url)
    if "folders" in parsed.path and identifier:
        return f"https://drive.google.com/drive/folders/{identifier}"
    if parsed.hostname and parsed.hostname.rstrip(".").casefold() == "docs.google.com" and identifier:
        if "/document/d/" in parsed.path:
            return f"https://docs.google.com/document/d/{identifier}/edit"
        if "/spreadsheets/d/" in parsed.path:
            return f"https://docs.google.com/spreadsheets/d/{identifier}/edit"
        if "/presentation/d/" in parsed.path:
            return f"https://docs.google.com/presentation/d/{identifier}/edit"
    if identifier:
        return f"https://drive.google.com/file/d/{identifier}/view"
    return parsed._replace(fragment="").geturl()


def is_drive_folder(url: str) -> bool:
    return is_public_drive_url(url) and "/folders/" in urlparse(url).path


def public_download_url(url: str) -> str:
    if not is_public_drive_url(url):
        return ""
    identifier = drive_id(url)
    parsed = urlparse(url)
    if not identifier:
        return url
    if "/document/d/" in parsed.path:
        return f"https://docs.google.com/document/d/{identifier}/export?format=pdf"
    if "/spreadsheets/d/" in parsed.path:
        return f"https://docs.google.com/spreadsheets/d/{identifier}/export?format=pdf"
    if "/presentation/d/" in parsed.path:
        return f"https://docs.google.com/presentation/d/{identifier}/export/pdf"
    return f"https://drive.google.com/uc?export=download&id={identifier}"


def exam_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", folded(value)) if token)


def _has_phrase(tokens: tuple[str, ...], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(tokens[index:index + len(phrase)] == phrase for phrase in phrases for index in range(len(tokens) - len(phrase) + 1))


EXAM_PHRASES = tuple(tuple(value.split()) for value in EXAM_FOLDER_HINTS)
MIDTERM_PHRASES = tuple(tuple(value.split()) for value in ("midterm", "mid term", "giua ky", "giua ki", "thi giua ky", "de giua ky", "gk"))
FINAL_PHRASES = tuple(tuple(value.split()) for value in ("final", "final exam", "thi cuoi ky", "de cuoi ky", "cuoi ky", "cuoi ki", "ck"))


def is_exam_context(label: str) -> bool:
    return _has_phrase(exam_tokens(label), EXAM_PHRASES)


def is_traversable_folder(label: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", folded(label))
    return is_exam_context(normalized) or any(hint in normalized for hint in GENERIC_PARENT_FOLDER_HINTS)


def classify_exam(label: str, *, in_exam_context: bool = False) -> str | None:
    tokens = exam_tokens(label)
    if _has_phrase(tokens, MIDTERM_PHRASES) and (in_exam_context or "gk" in tokens or "midterm" in tokens or _has_phrase(tokens, (("mid", "term"), ("thi", "giua", "ky"), ("de", "giua", "ky")))):
        return "midterm"
    if _has_phrase(tokens, FINAL_PHRASES) and (in_exam_context or "ck" in tokens or _has_phrase(tokens, (("final", "exam"), ("exam", "final"), ("thi", "cuoi", "ky"), ("de", "cuoi", "ky"))) or ("final" in tokens and any(token.startswith("hk") for token in tokens))):
        return "final"
    return "unknown_exam" if in_exam_context else None


def infer_term(label: str, *, in_exam_context: bool = False) -> str:
    values = [token.upper() for token in exam_tokens(label) if re.fullmatch(r"(?:hk)?\d{3}|20\d{2}", token)]
    ranges = re.findall(r"20\d{2}\s*-\s*20\d{2}", folded(label))
    value = (ranges[0].replace(" ", "") if ranges else (values[0] if values else ""))
    if not value:
        return ""
    return value if (value.startswith("HK") or value.startswith("20") or in_exam_context) else ""


@dataclass(frozen=True)
class DriveItem:
    url: str
    name: str
    is_folder: bool = False
    path_label: str = ""


@dataclass(frozen=True)
class ExamCandidate:
    stable_id: str
    url: str
    name: str
    exam_type: str
    term: str = ""
    path_label: str = ""
    exam_variant: str = "unknown"


@dataclass(frozen=True)
class DriveTraversalNode:
    item: DriveItem
    depth: int
    exam_context: bool = False
    exam_type_context: str = ""
    exam_variant: str = "unknown"


@dataclass
class ExamDiscovery:
    candidates: list[ExamCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    folder_results: list["FolderEnumeration"] = field(default_factory=list)
    state_counts: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "completed"
    overall_timeout: bool = False
    queued_folders_remaining: int = 0

    def record_state(self, state: str) -> None:
        self.state_counts[state] = self.state_counts.get(state, 0) + 1


@dataclass
class FolderEnumeration:
    items: list[DriveItem] = field(default_factory=list)
    state: str = "public_empty"
    mode: str = "http"
    warning: str = ""
    drive_id: str = ""
    path_label: str = ""
    depth: int = 0
    exam_context: bool = False
    exam_type_context: str = ""
    exam_variant: str = "unknown"
    retry_count: int = 0


@dataclass(frozen=True)
class CachedExam:
    stable_id: str
    path: str
    sha256: str
    size: int
    etag: str = ""
    last_modified: str = ""
    cached_at: int = 0


def default_exam_cache_dir() -> Path:
    return user_config_dir() / "coursewave-cache"


class ExamCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else default_exam_cache_dir()
        self.index_path = self.root / "exam_index.json"

    def _load(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, payload: dict[str, dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False, suffix=".tmp") as handle:
            temp = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            os.replace(temp, self.index_path)
        finally:
            temp.unlink(missing_ok=True)

    def get(self, stable_id: str, *, max_age_seconds: int | None = EXAM_CACHE_FRESHNESS_SECONDS) -> CachedExam | None:
        item = self._load().get(stable_id)
        if not isinstance(item, dict):
            return None
        path = self.root / str(item.get("path", ""))
        if not path.is_file():
            return None
        cached_at = int(item.get("cached_at", 0) or 0)
        if max_age_seconds is not None and time.time() - cached_at > max_age_seconds:
            return None
        digest = sha256_file(path)
        if not digest or digest != item.get("sha256"):
            return None
        return CachedExam(stable_id, str(path), digest, path.stat().st_size, str(item.get("etag", "")), str(item.get("last_modified", "")), cached_at)

    def put(self, stable_id: str, source: Path, *, etag: str = "", last_modified: str = "") -> CachedExam:
        self.root.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower() or ".bin"
        destination = self.root / f"{safe_name(stable_id, 96)}{suffix}"
        temp = destination.with_suffix(destination.suffix + ".part")
        try:
            temp.write_bytes(source.read_bytes())
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        digest = sha256_file(destination)
        payload = self._load()
        payload[stable_id] = {
            "path": destination.name,
            "sha256": digest,
            "etag": etag,
            "last_modified": last_modified,
            "cached_at": int(time.time()),
        }
        self._save(payload)
        return CachedExam(stable_id, str(destination), digest, destination.stat().st_size, etag, last_modified, int(payload[stable_id]["cached_at"]))

    def touch(self, stable_id: str) -> None:
        payload = self._load()
        if stable_id in payload:
            payload[stable_id]["cached_at"] = int(time.time())
            self._save(payload)


class DriveMetadataCache:
    """Short-lived public folder listings, kept separately from exam payload cache."""

    def __init__(self, root: Path | None = None):
        self.path = (Path(root) if root is not None else default_exam_cache_dir()) / "drive_index.json"

    def load(self, url: str, *, max_age_seconds: int = 6 * 60 * 60) -> list[DriveItem] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != DRIVE_METADATA_CACHE_SCHEMA_VERSION:
                return None
            entry = payload.get(canonical_drive_url(url), {})
            if time.time() - float(entry.get("fetched_at", 0)) > max_age_seconds:
                return None
            return [DriveItem(**item) for item in entry.get("items", []) if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            return None

    def save(self, url: str, items: Iterable[DriveItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except (OSError, ValueError):
            payload = {}
        payload["schema_version"] = DRIVE_METADATA_CACHE_SCHEMA_VERSION
        payload[canonical_drive_url(url)] = {"fetched_at": time.time(), "items": [asdict(item) for item in items]}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp") as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(256 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


class GoogleDriveProvider:
    """Bounded public-link provider; inaccessible folders remain non-fatal warnings."""

    def __init__(self, session: requests.Session | None = None, *, timeout=DRIVE_TIMEOUT, max_depth: int = 8, max_items: int = 200, metadata_cache: DriveMetadataCache | None = None, browser_enumerator: PublicDriveBrowserEnumerator | None = None, total_timeout_seconds: float = MAX_TRAVERSAL_SECONDS):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_depth = max_depth
        self.max_items = max_items
        self.metadata_cache = metadata_cache or DriveMetadataCache()
        self.browser_enumerator = browser_enumerator or PublicDriveBrowserEnumerator()
        self.total_timeout_seconds = total_timeout_seconds

    def _get(self, url: str, *, headers: dict[str, str] | None = None) -> requests.Response:
        return self.session.get(url, timeout=self.timeout, allow_redirects=True, headers=headers)

    def _folder_items(self, item: DriveItem, *, cancel_event: Event | None = None, progress_callback=None, high_priority: bool = False) -> FolderEnumeration:
        cached = self.metadata_cache.load(item.url)
        if cached is not None:
            return FolderEnumeration(cached, "public_enumerated", "cache", drive_id=drive_id(item.url), path_label=item.path_label)
        response = self._get(item.url)
        try:
            if response.status_code in {401, 403}:
                return FolderEnumeration(state="permission_denied", warning="Không có quyền truy cập thư mục Google Drive công khai.")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            found: list[DriveItem] = []
            for anchor in soup.find_all("a", href=True):
                url = anchor["href"]
                if not is_public_drive_url(url) or not drive_id(url):
                    continue
                name = anchor.get_text(" ", strip=True) or item.name
                found.append(DriveItem(url=canonical_drive_url(url), name=name, is_folder=is_drive_folder(url), path_label=f"{item.path_label}/{name}".strip("/")))
            if found:
                self.metadata_cache.save(item.url, found)
                return FolderEnumeration(found, "public_enumerated", "http")
            # Drive commonly renders public listings only after JavaScript.
            # The isolated browser sees the same anonymous public view.
            browser = self.browser_enumerator.enumerate(item.url, max_items=self.max_items, cancel_event=cancel_event, progress_callback=progress_callback)
            converted = [
                DriveItem(entry.url, entry.name, entry.is_folder, f"{item.path_label}/{entry.name}".strip("/"))
                for entry in browser.items
            ]
            if converted:
                self.metadata_cache.save(item.url, converted)
            result = FolderEnumeration(converted, browser.state, browser.mode, browser.warning, drive_id(item.url), item.path_label)
            if result.state == "timeout" and high_priority:
                retry = self.browser_enumerator.enumerate(item.url, max_items=self.max_items, cancel_event=cancel_event, progress_callback=progress_callback)
                result.retry_count = 1
                result.mode = retry.mode
                result.state = retry.state
                result.warning = retry.warning
                result.items = [DriveItem(entry.url, entry.name, entry.is_folder, f"{item.path_label}/{entry.name}".strip("/")) for entry in retry.items]
            return result
        except requests.RequestException as exc:
            return FolderEnumeration(state="http_fetch_failed", warning=f"Không thể đọc Google Drive: {type(exc).__name__}")
        finally:
            response.close()

    def discover(self, urls: Iterable[str | DriveItem], *, cancel_event: Event | None = None, progress_callback=None) -> ExamDiscovery:
        result = ExamDiscovery()
        queue: list[tuple[int, int, DriveTraversalNode]] = []
        sequence = 0
        for raw in urls:
            url = raw.url if isinstance(raw, DriveItem) else raw
            canonical = canonical_drive_url(url)
            if canonical:
                name = raw.name if isinstance(raw, DriveItem) else canonical
                heapq.heappush(queue, (0, sequence, DriveTraversalNode(DriveItem(canonical, name, is_folder=is_drive_folder(canonical), path_label=""), 0)))
                sequence += 1
        seen: set[str] = set()
        deadline = time.monotonic() + self.total_timeout_seconds
        def record_file(item: DriveItem, context: bool, type_context: str, variant: str) -> None:
            suffix = Path(item.name).suffix.lower()
            exam_type = classify_exam(f"{item.path_label} {item.name}", in_exam_context=context) or (type_context if context else None)
            if exam_type and suffix in SUPPORTED_EXAM_SUFFIXES:
                stable = drive_id(item.url) or hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:20]
                result.candidates.append(ExamCandidate(stable, item.url, safe_name(item.name, 150), exam_type, infer_term(f"{item.path_label} {item.name}", in_exam_context=context), item.path_label, variant))
            elif exam_type:
                result.record_state("unsupported_item")
        while queue and len(seen) < self.max_items and time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                result.warnings.append("Đã hủy quét đề thi Coursewave.")
                break
            _priority, _sequence, node = heapq.heappop(queue)
            item, depth = node.item, node.depth
            identity = canonical_drive_url(item.url)
            if identity in seen:
                continue
            seen.add(identity)
            own_type = classify_exam(item.name)
            context = node.exam_context or is_exam_context(f"{item.path_label} {item.name}")
            type_context = own_type or node.exam_type_context
            variant = "official" if any(token in folded(item.name) for token in ("chinh thuc", "official")) else ("sample" if any(token in folded(item.name) for token in ("minh hoa", "sample", "demo")) else node.exam_variant)
            if item.is_folder:
                if depth >= self.max_depth:
                    result.warnings.append("Đã đạt giới hạn độ sâu thư mục Drive.")
                    result.record_state("depth_limit")
                    continue
                enumeration = self._folder_items(item, cancel_event=cancel_event, progress_callback=progress_callback, high_priority=context or bool(type_context))
                enumeration.depth = depth
                enumeration.exam_context = context
                enumeration.exam_type_context = type_context
                enumeration.exam_variant = variant
                result.folder_results.append(enumeration)
                result.record_state(enumeration.state)
                if enumeration.warning:
                    result.warnings.append(enumeration.warning)
                children = sorted(enumeration.items, key=lambda child: not is_exam_context(f"{child.path_label} {child.name}"))
                for child in children:
                    if not child.is_folder:
                        record_file(child, context, type_context, variant)
                        continue
                    child_type = classify_exam(child.name)
                    child_context = context or is_exam_context(f"{child.path_label} {child.name}")
                    if child.is_folder and not (child_context or is_traversable_folder(f"{child.path_label} {child.name}")):
                        result.record_state("skipped_non_exam_folder")
                        continue
                    priority = 0 if child_type else (1 if child_context else 3)
                    heapq.heappush(queue, (priority, sequence, DriveTraversalNode(child, depth + 1, child_context, child_type or type_context, variant)))
                    sequence += 1
                continue
            record_file(item, context, type_context, variant)
        if queue:
            result.stop_reason = "node_limit" if len(seen) >= self.max_items else "overall_timeout"
            result.overall_timeout = result.stop_reason == "overall_timeout"
            result.queued_folders_remaining = len(queue)
            result.record_state(result.stop_reason)
        deduped = {candidate.stable_id: candidate for candidate in result.candidates}
        result.candidates = list(deduped.values())
        return result

    def download(self, candidate: ExamCandidate, target_dir: Path, *, cancel_event: Event | None = None, conditional_headers: dict[str, str] | None = None) -> tuple[Path | None, str, str, str]:
        """Download a public source through a bounded stream; never writes outside target_dir."""
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(candidate.name).suffix.lower() or ".bin"
        target = target_dir / f"{safe_name(candidate.stable_id, 96)}{suffix}"
        temp = target.with_suffix(target.suffix + ".part")
        response = None
        try:
            response = self._get(public_download_url(candidate.url), headers=conditional_headers)
            if response.status_code == 304:
                return None, response.headers.get("ETag", ""), response.headers.get("Last-Modified", ""), "not_modified"
            if response.status_code in {401, 403}:
                return None, "", "", "Cần quyền truy cập Google Drive bổ sung."
            response.raise_for_status()
            total = 0
            with temp.open("wb") as handle:
                for chunk in response.iter_content(64 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        return None, "", "", "Đã hủy tải đề thi."
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_EXAM_BYTES:
                        return None, "", "", "Tệp đề thi vượt giới hạn an toàn."
                    handle.write(chunk)
            os.replace(temp, target)
            return target, response.headers.get("ETag", ""), response.headers.get("Last-Modified", ""), ""
        except requests.RequestException as exc:
            return None, "", "", f"Không thể tải đề thi: {type(exc).__name__}"
        finally:
            temp.unlink(missing_ok=True)
            if response is not None:
                response.close()
