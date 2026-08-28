from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import Event
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import (
    DEEP_MODS,
    HTML_RESPONSE_DEADLINE,
    INTERACTIVE_MODS,
    MAX_REQUEST_ATTEMPTS,
    REQUEST_CONNECT_TIMEOUT,
    REQUEST_READ_TIMEOUT,
    REQUEST_RETRY_BACKOFF,
    RESOURCE_OPEN_DEADLINE,
    STREAM_HEARTBEAT_INTERVAL,
    STREAM_MAX_TOTAL_TIMEOUT,
    STREAM_MIN_TOTAL_TIMEOUT,
    STREAM_SECONDS_PER_MIB,
    STREAM_UNKNOWN_TOTAL_TIMEOUT,
    TITLE_LOOKUP_DEADLINE,
)
from .layout import bucket_name_for_section, context_prefix
from .models import Section
from .parser import (
    choose_content_root,
    extract_section_content,
    parse_sections,
    sanitize_content_html,
)
from .utils import (
    activity_type,
    clean_text,
    filename_from_response,
    html_response,
    is_course_url,
    is_probably_file_url,
    is_same_lms,
    is_video_response,
    is_video_url,
    normalize_url,
    safe_name,
    write_json,
)

EventCallback = Callable[[dict], None]


class SyncCancelled(RuntimeError):
    """Raised only for the cooperative, user-requested sync cancellation."""


class ResourceTimeout(requests.Timeout):
    """A bounded LMS resource deadline elapsed without completing the resource."""


class AuthenticationError(RuntimeError):
    """The copied Chrome session no longer reaches authenticated LMS content."""


class DeepDownloader:
    """BK-LMS crawler with a deliberately shallow output layout.

    The crawler may follow Moodle links deeply, but downloaded files are flattened
    into a small set of user-facing folders (Bài giảng/Lab/Bài tập/etc.).
    """

    def __init__(
        self,
        session: requests.Session,
        output: Path,
        force: bool = False,
        max_depth: int = 4,
        follow_linked_courses: bool = True,
        event_callback: Optional[EventCallback] = None,
        cancel_event: Event | None = None,
    ):
        self.session = session
        self.output = output
        self.force = force
        self.max_depth = max_depth
        self.follow_linked_courses = follow_linked_courses
        self.event_callback = event_callback
        self.cancel_event = cancel_event

        self.visited: set[str] = set()
        self.course_visited: set[str] = set()
        self.manifest: list[dict] = []
        self.course_structures: list[dict] = []
        self.root_course_dir: Optional[Path] = None
        self.root_course_name: Optional[str] = None
        self.known_sources: dict[Path, str] = {}

        self.stats = {
            "downloaded": 0,
            "skipped": 0,
            "skipped_video": 0,
            "pages_saved": 0,
            "errors": 0,
        }

    def emit(self, event: str, message: str = "", **payload) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback({"event": event, "message": message, **payload})
        except Exception:
            pass

    def log(self, **record) -> None:
        self.manifest.append(record)
        if record.get("path") and record.get("source"):
            self.known_sources[Path(record["path"])] = str(record["source"])
        if record.get("status") == "error":
            detail = record.get("error") or record.get("source") or "Unknown error"
            self.emit("error", f"Lỗi: {detail}", **record)

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SyncCancelled("Đã hủy đồng bộ.")

    @staticmethod
    def _resource_name(resource_name: str | None) -> str:
        return clean_text(resource_name or "") or "tài nguyên BK-LMS"

    def _timeout_error(self, resource_name: str | None) -> ResourceTimeout:
        name = self._resource_name(resource_name)
        self.emit(
            "resource_timeout",
            f"Quá thời gian chờ, đã bỏ qua: {name}",
            resource_name=name,
        )
        return ResourceTimeout(f"Quá thời gian chờ: {name}")

    def _wait_for_retry(self, delay: float) -> None:
        if self.cancel_event is None:
            time.sleep(delay)
        elif self.cancel_event.wait(delay):
            self._check_cancelled()

    @staticmethod
    def _retryable(exc: requests.RequestException, status_code: int) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        return isinstance(exc, requests.HTTPError) and (
            status_code == 408 or status_code == 429 or status_code >= 500
        )

    def fetch(
        self,
        url: str,
        stream: bool = True,
        *,
        resource_name: str | None = None,
        max_attempts: int = MAX_REQUEST_ATTEMPTS,
        deadline_seconds: float = RESOURCE_OPEN_DEADLINE,
    ) -> requests.Response:
        """Open one resource with capped retries and separate socket timeouts.

        ``requests`` only applies its timeout to inactivity on an individual
        socket operation.  The monotonic deadline here additionally caps the
        whole opening/retry phase, while file and HTML bodies are bounded by
        their dedicated readers below.
        """
        del stream  # Bodies are always read explicitly below so they are bounded too.
        name = self._resource_name(resource_name)
        attempts = max(1, min(MAX_REQUEST_ATTEMPTS, max_attempts))
        deadline = time.monotonic() + deadline_seconds
        self._check_cancelled()
        self.emit("resource_opening", f"Đang mở: {name}", resource_name=name)

        for attempt in range(attempts):
            response: Optional[requests.Response] = None
            try:
                self._check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self._timeout_error(name)
                response = self.session.get(
                    url,
                    stream=True,
                    allow_redirects=True,
                    timeout=(
                        min(REQUEST_CONNECT_TIMEOUT, max(1, remaining)),
                        min(REQUEST_READ_TIMEOUT, max(1, remaining)),
                    ),
                )
                response.raise_for_status()
                if "/login/" in urlparse(response.url).path.lower():
                    response.close()
                    raise AuthenticationError(
                        "Phiên đăng nhập BK-LMS chưa hợp lệ hoặc đã hết hạn. "
                        "Hãy đăng nhập lại trong Chrome."
                    )
                return response
            except SyncCancelled:
                if response is not None:
                    response.close()
                raise
            except AuthenticationError:
                raise
            except ResourceTimeout:
                if response is not None:
                    response.close()
                raise
            except requests.RequestException as exc:
                status_code = getattr(response, "status_code", 0) if response is not None else 0
                if response is not None:
                    response.close()
                retryable = self._retryable(exc, status_code)
                if not retryable or attempt == attempts - 1:
                    if isinstance(exc, requests.Timeout):
                        raise self._timeout_error(name) from exc
                    raise
                delay = REQUEST_RETRY_BACKOFF * (2**attempt)
                if time.monotonic() + delay >= deadline:
                    raise self._timeout_error(name) from exc
                self.emit(
                    "resource_retry",
                    f"Thử lại {attempt + 2}/{attempts}: {name}",
                    resource_name=name,
                    attempt=attempt + 2,
                    attempts=attempts,
                )
                self._wait_for_retry(delay)
        raise self._timeout_error(name)

    def read_response_bytes(
        self,
        response: requests.Response,
        resource_name: str | None,
    ) -> bytes:
        """Read an HTML-style response under a short absolute body deadline."""
        name = self._resource_name(resource_name)
        deadline = time.monotonic() + HTML_RESPONSE_DEADLINE
        chunks: list[bytes] = []
        for chunk in response.iter_content(64 * 1024):
            self._check_cancelled()
            if time.monotonic() > deadline:
                raise self._timeout_error(name)
            if chunk:
                chunks.append(chunk)
        self._check_cancelled()
        if time.monotonic() > deadline:
            raise self._timeout_error(name)
        return b"".join(chunks)

    def read_response_text(
        self,
        response: requests.Response,
        resource_name: str | None,
    ) -> str:
        return self.read_response_bytes(response, resource_name).decode(
            response.encoding or "utf-8",
            errors="replace",
        )

    @staticmethod
    def _stream_total_timeout(response: requests.Response) -> float:
        size_raw = response.headers.get("Content-Length", "")
        if not size_raw.isdigit():
            return STREAM_UNKNOWN_TOTAL_TIMEOUT
        size_mib = int(size_raw) / (1024 * 1024)
        return min(
            STREAM_MAX_TOTAL_TIMEOUT,
            max(STREAM_MIN_TOTAL_TIMEOUT, size_mib * STREAM_SECONDS_PER_MIB),
        )

    def _bucket_dir(self, section_title: str) -> Path:
        if self.root_course_dir is None:
            raise RuntimeError("Chưa khởi tạo thư mục course gốc.")
        path = self.root_course_dir / bucket_name_for_section(section_title)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _meta_dir(self) -> Path:
        if self.root_course_dir is None:
            raise RuntimeError("Chưa khởi tạo thư mục course gốc.")
        path = self.root_course_dir / "_meta"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_response_file(
        self,
        response: requests.Response,
        dest_dir: Path,
        fallback: str,
        source: str,
        context: str,
        prefix: str = "",
    ) -> Optional[Path]:
        if is_video_response(response):
            self.stats["skipped_video"] += 1
            self.log(
                status="skipped_video",
                context=context,
                source=source,
                final_url=response.url,
            )
            self.emit("video_skipped", f"Bỏ qua video: {fallback}", source=source)
            print(f"    [VIDEO SKIP] {fallback}")
            response.close()
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = filename_from_response(response, fallback)
        if prefix:
            filename = safe_name(prefix + filename, 190)

        target = self._unique_target(dest_dir / filename, source)
        remote_size_raw = response.headers.get("Content-Length", "")
        remote_size = (
            int(remote_size_raw) if remote_size_raw.isdigit() else None
        )

        if target.exists() and not self.force:
            if remote_size is None or target.stat().st_size == remote_size:
                print(f"    [SKIP] {target.name}")
                self.stats["skipped"] += 1
                self.log(
                    status="skipped",
                    context=context,
                    source=source,
                    path=str(target),
                )
                self.emit(
                    "file_skipped",
                    f"Đã có: {target.name}",
                    path=str(target),
                )
                response.close()
                return target

        self._check_cancelled()
        temp = target.with_suffix(target.suffix + ".part")
        deadline = time.monotonic() + self._stream_total_timeout(response)
        last_heartbeat = time.monotonic()
        bytes_written = 0
        self.emit(
            "file_downloading",
            f"Đang tải: {filename}",
            filename=filename,
            resource_name=filename,
        )
        try:
            with temp.open("wb") as file_obj:
                for chunk in response.iter_content(256 * 1024):
                    self._check_cancelled()
                    now = time.monotonic()
                    if now > deadline:
                        raise self._timeout_error(filename)
                    if chunk:
                        file_obj.write(chunk)
                        bytes_written += len(chunk)
                    if now - last_heartbeat >= STREAM_HEARTBEAT_INTERVAL:
                        self.emit(
                            "download_progress",
                            f"Đang tải: {filename}",
                            filename=filename,
                            bytes_written=bytes_written,
                            resource_name=filename,
                        )
                        last_heartbeat = now

            self._check_cancelled()
            if time.monotonic() > deadline:
                raise self._timeout_error(filename)

            if target.exists():
                target.unlink()
            temp.replace(target)

            size = target.stat().st_size
            print(f"    [OK]   {target.name}")
            self.stats["downloaded"] += 1
            self.log(
                status="downloaded",
                context=context,
                source=source,
                final_url=response.url,
                path=str(target),
                size=size,
            )
            self.emit(
                "file_downloaded",
                f"Đã tải: {target.name}",
                path=str(target),
                size=size,
            )
            return target
        except SyncCancelled:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
            self.emit("cancelled", f"Đã hủy: {filename}", filename=filename)
            raise
        except Exception:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
            raise
        finally:
            response.close()

    def download_media_links(
        self,
        media_links: Iterable[tuple[str, str]],
        dest_dir: Path,
        context: str,
        prefix: str,
    ) -> None:
        seen: set[str] = set()
        index = 0

        for label, url in media_links:
            self._check_cancelled()
            url = normalize_url(url)
            if url in seen:
                continue
            seen.add(url)

            if is_video_url(url):
                self.stats["skipped_video"] += 1
                self.log(status="skipped_video", context=context, source=url)
                self.emit(
                    "video_skipped",
                    f"Bỏ qua video: {label or url}",
                    source=url,
                )
                print(f"    [VIDEO SKIP] {label or url}")
                continue

            index += 1
            try:
                response = self.fetch(url, resource_name=label or "tệp đính kèm")
                if html_response(response):
                    print(f"    [INFO] Media trả HTML, bỏ qua: {url}")
                    response.close()
                    continue

                media_prefix = f"{prefix}{index:02d} - " if prefix else f"{index:02d} - "
                self.save_response_file(
                    response,
                    dest_dir,
                    label or "asset",
                    url,
                    context,
                    prefix=media_prefix,
                )
            except SyncCancelled:
                raise
            except AuthenticationError:
                raise
            except Exception as exc:
                print(f"    [ERR] asset {url}: {exc}")
                self.stats["errors"] += 1
                self.log(
                    status="error",
                    context=context,
                    source=url,
                    error=str(exc),
                )

    def save_html_page(
        self,
        html: str,
        page_url: str,
        dest_dir: Path,
        title: str,
        context: str,
        prefix: str,
    ) -> list[str]:
        """Save useful page text/assets directly inside the section bucket."""
        soup = BeautifulSoup(html, "html.parser")
        root = choose_content_root(soup)
        html_doc, media_links, content_links = sanitize_content_html(
            root,
            page_url,
        )

        dest_dir.mkdir(parents=True, exist_ok=True)
        text = clean_text(
            BeautifulSoup(html_doc, "html.parser").get_text("\n", strip=True)
        )

        if text:
            base_name = prefix.rstrip(" -") or title
            text_name = safe_name(f"{base_name}.txt", 190)
            text_path = dest_dir / text_name
            text_path.write_text(text + "\n", encoding="utf-8")
            self.stats["pages_saved"] += 1
            self.log(
                status="page_saved",
                context=context,
                source=page_url,
                path=str(text_path),
            )
            self.emit(
                "page_saved",
                f"Đã lưu nội dung: {title}",
                path=str(text_path),
            )
            print(f"    [PAGE] {text_path.name}")

        if media_links:
            self.download_media_links(
                media_links,
                dest_dir,
                context,
                prefix=prefix or (safe_name(title, 80) + " - "),
            )

        # External shortcuts and raw HTML are intentionally not preserved.
        return [url for url in content_links if is_same_lms(url)]

    def _unique_target(self, target: Path, source: str) -> Path:
        """Keep same-named but distinct LMS resources from overwriting each other."""
        candidate = target
        index = 2
        while candidate.exists() and self.known_sources.get(candidate) not in (None, source):
            candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
            index += 1
        return candidate

    def _load_known_sources(self, course_dir: Path) -> None:
        manifest_path = course_dir / "_meta" / "download_manifest.json"
        try:
            records = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(records, list):
            return
        for record in records:
            if not isinstance(record, dict):
                continue
            path, source = record.get("path"), record.get("source")
            if path and source:
                self.known_sources[Path(path)] = str(source)

    def crawl_moodle_link(
        self,
        url: str,
        dest_dir: Path,
        title: str,
        depth: int,
        context: str,
        prefix: str,
    ) -> None:
        self._check_cancelled()
        url = normalize_url(url)
        if depth > self.max_depth:
            print(f"    [DEPTH] Bỏ qua vì vượt max-depth: {url}")
            self.log(status="max_depth", context=context, source=url)
            return

        if is_course_url(url):
            if self.follow_linked_courses:
                self.crawl_course(url, dest_dir, depth, linked_title=title)
            else:
                self.emit(
                    "linked_course_skipped",
                    f"Bỏ qua course liên kết: {title}",
                )
            return

        if url in self.visited:
            print(f"    [VISITED] {url}")
            return
        self.visited.add(url)

        mod = activity_type(url)
        if mod in INTERACTIVE_MODS:
            self.emit("interactive_skipped", f"Bỏ qua {mod}: {title}")
            return

        try:
            response = self.fetch(url, resource_name=title)
        except SyncCancelled:
            raise
        except AuthenticationError:
            raise
        except Exception as exc:
            print(f"    [ERR] {url}: {exc}")
            self.stats["errors"] += 1
            self.log(
                status="error",
                context=context,
                source=url,
                error=str(exc),
            )
            return

        final_url = normalize_url(response.url)

        if is_course_url(final_url):
            response.close()
            if self.follow_linked_courses:
                self.crawl_course(
                    final_url,
                    dest_dir,
                    depth,
                    linked_title=title,
                )
            return

        if not html_response(response):
            try:
                self.save_response_file(
                    response,
                    dest_dir,
                    title,
                    url,
                    context,
                    prefix=prefix,
                )
            except SyncCancelled:
                raise
            except Exception as exc:
                # The transfer removes its temporary file before raising.  Log
                # this one resource once and continue with sibling links.
                self.stats["errors"] += 1
                self.log(
                    status="error",
                    context=context,
                    source=url,
                    error=str(exc),
                )
            return

        if not is_same_lms(final_url):
            response.close()
            return

        try:
            html = self.read_response_text(response, title)
        except SyncCancelled:
            raise
        except Exception as exc:
            self.stats["errors"] += 1
            self.log(
                status="error",
                context=context,
                source=url,
                error=str(exc),
            )
            return
        finally:
            response.close()

        nested_links = self.save_html_page(
            html,
            final_url,
            dest_dir,
            title,
            context,
            prefix,
        )

        if mod == "book":
            book_soup = BeautifulSoup(html, "html.parser")
            for anchor in book_soup.select(
                "a[href*='/mod/book/view.php']"
            ):
                href = anchor.get("href")
                if href:
                    nested_links.append(
                        normalize_url(urljoin(final_url, href))
                    )

        filtered: list[str] = []
        seen: set[str] = set()

        for link in nested_links:
            link = normalize_url(link)
            if link in seen or link == final_url:
                continue
            seen.add(link)

            link_type = activity_type(link)
            if (
                link_type == "pluginfile"
                or is_probably_file_url(link)
                or link_type in DEEP_MODS
                or link_type == "course"
            ):
                filtered.append(link)

        for index, link in enumerate(filtered, start=1):
            self._check_cancelled()
            link_type = activity_type(link)

            if link_type == "pluginfile" or is_probably_file_url(link):
                try:
                    file_response = self.fetch(link, resource_name=f"{title} — tệp đính kèm")
                    if html_response(file_response):
                        file_response.close()
                        continue
                    self.save_response_file(
                        file_response,
                        dest_dir,
                        f"linked_{index}",
                        link,
                        context,
                        prefix=f"{prefix}{index:02d} - ",
                    )
                except SyncCancelled:
                    raise
                except AuthenticationError:
                    raise
                except Exception as exc:
                    print(f"    [ERR] nested file {link}: {exc}")
                    self.stats["errors"] += 1
                    self.log(
                        status="error",
                        context=context,
                        source=link,
                        error=str(exc),
                    )
                continue

            nested_name = self.link_title(link) or f"nested_{index}_{link_type}"
            print(f"    -> đi sâu [{link_type}] {nested_name}")
            nested_prefix = (
                f"{prefix}{safe_name(nested_name, 70)} - "
                if prefix
                else f"{safe_name(nested_name, 70)} - "
            )
            try:
                self.crawl_moodle_link(
                    link,
                    dest_dir,
                    nested_name,
                    depth + 1,
                    context,
                    nested_prefix,
                )
            except SyncCancelled:
                raise
            except AuthenticationError:
                raise
            except Exception as exc:
                self.stats["errors"] += 1
                self.log(
                    status="error",
                    context=context,
                    source=link,
                    error=str(exc),
                )

    def link_title(self, url: str) -> Optional[str]:
        response: Optional[requests.Response] = None
        try:
            response = self.fetch(
                url,
                stream=False,
                resource_name="liên kết",
                max_attempts=1,
                deadline_seconds=TITLE_LOOKUP_DEADLINE,
            )
            if not html_response(response):
                return None

            soup = BeautifulSoup(self.read_response_text(response, "liên kết"), "html.parser")
            for selector in (
                ".page-header-headings h1",
                "#region-main h2",
                "h1",
                "h2",
                "title",
            ):
                node = soup.select_one(selector)
                if node:
                    text = clean_text(node.get_text(" ", strip=True))
                    text = re.sub(
                        r"\s*\|\s*BK-LMS\s*$",
                        "",
                        text,
                        flags=re.I,
                    )
                    if text:
                        return text
        except SyncCancelled:
            raise
        except AuthenticationError:
            raise
        except Exception:
            return None
        finally:
            if response is not None:
                response.close()
        return None

    def save_section_inline_content(
        self,
        section: Section,
        dest_dir: Path,
        course_url: str,
    ) -> None:
        self._check_cancelled()
        html_doc, media_links, _ = extract_section_content(
            section.node_html,
            course_url,
        )
        if not html_doc:
            return

        prefix = context_prefix(section.title)
        text = clean_text(
            BeautifulSoup(html_doc, "html.parser").get_text("\n", strip=True)
        )

        if text:
            text_path = dest_dir / safe_name(
                f"{prefix}Ghi chú.txt",
                190,
            )
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text + "\n", encoding="utf-8")
            self.stats["pages_saved"] += 1
            print(f"  [INLINE] {text_path.name}")

        if media_links:
            self.download_media_links(
                media_links,
                dest_dir,
                f"section:{section.title}",
                prefix=prefix,
            )

    def crawl_course(
        self,
        course_url: str,
        parent_dir: Path,
        depth: int = 0,
        linked_title: Optional[str] = None,
    ) -> Optional[Path]:
        self._check_cancelled()
        course_url = normalize_url(course_url)

        if course_url in self.course_visited:
            print(f"  [COURSE VISITED] {course_url}")
            return self.root_course_dir
        self.course_visited.add(course_url)

        self.emit(
            "course_start",
            f"Đang quét course: {course_url}",
            url=course_url,
            depth=depth,
        )
        print("\n" + "#" * 78)
        print(f"CRAWL COURSE depth={depth}: {course_url}")
        print("#" * 78)

        try:
            page = self.fetch(
                course_url,
                stream=False,
                resource_name=linked_title or "trang khóa học",
            )
        except SyncCancelled:
            raise
        except AuthenticationError:
            raise
        except Exception as exc:
            print(f"[ERR] Không mở được course: {exc}")
            self.stats["errors"] += 1
            self.log(
                status="error",
                context="course",
                source=course_url,
                error=str(exc),
            )
            return None

        try:
            final_path = urlparse(page.url).path.lower()
            if "/login/" in final_path:
                message = (
                    "Phiên đăng nhập BK-LMS chưa hợp lệ hoặc đã hết hạn. "
                    "Hãy đăng nhập lại trong Chrome."
                )
                self.stats["errors"] += 1
                self.log(
                    status="error",
                    context="course",
                    source=course_url,
                    error=message,
                )
                if depth == 0:
                    raise RuntimeError(message)
                return None

            if not html_response(page):
                message = "Course URL không trả về trang HTML của BK-LMS."
                self.stats["errors"] += 1
                self.log(
                    status="error",
                    context="course",
                    source=course_url,
                    error=message,
                )
                if depth == 0:
                    raise RuntimeError(message)
                return None

            course_name, sections = parse_sections(
                self.read_response_text(page, linked_title or "trang khóa học"),
                page.url,
            )
        finally:
            page.close()

        if depth == 0:
            course_dir = parent_dir / safe_name(course_name, 150)
            self.root_course_dir = course_dir
            self.root_course_name = course_name
            course_dir.mkdir(parents=True, exist_ok=True)
            self._load_known_sources(course_dir)
        else:
            if self.root_course_dir is None:
                raise RuntimeError("Linked course được crawl trước course gốc.")
            course_dir = self.root_course_dir

        print(f"Tên course: {course_name}")
        print(f"Sections:   {len(sections)}")
        print(f"Output:     {course_dir}")
        if depth > 0 and linked_title:
            print(f"Linked từ:  {linked_title}")

        structure = {
            "course_name": course_name,
            "course_url": course_url,
            "depth": depth,
            "linked_title": linked_title,
            "sections": [
                {
                    "index": section.index,
                    "title": section.title,
                    "bucket": bucket_name_for_section(section.title),
                    "activities": [
                        {
                            "order": activity.order,
                            "name": activity.name,
                            "url": activity.url,
                            "type": activity.mod_type,
                        }
                        for activity in section.activities
                    ],
                }
                for section in sections
            ],
        }
        self.course_structures.append(structure)

        for section in sections:
            self._check_cancelled()
            bucket_dir = self._bucket_dir(section.title)

            self.emit(
                "section_start",
                f"{section.index:02d}. {section.title}",
                section_index=section.index,
                section_title=section.title,
                activity_count=len(section.activities),
                bucket=bucket_dir.name,
            )
            print("\n" + "=" * 78)
            print(
                f"{section.index:02d}. {section.title} "
                f"-> {bucket_dir.name} "
                f"({len(section.activities)} activity)"
            )
            print("=" * 78)

            self.save_section_inline_content(
                section,
                bucket_dir,
                course_url,
            )

            for activity in section.activities:
                self._check_cancelled()
                mod = activity.mod_type
                context = (
                    f"{course_name} > {section.title} > {activity.name}"
                )
                section_prefix = context_prefix(section.title)
                activity_prefix = context_prefix(
                    section.title,
                    activity.name,
                )

                print(f"\n  [{mod}] {activity.name}")
                self.emit(
                    "activity_processing",
                    f"Đang xử lý: {activity.name}",
                    activity_name=activity.name,
                    section_title=section.title,
                )

                if mod in INTERACTIVE_MODS:
                    self.emit(
                        "interactive_skipped",
                        f"Bỏ qua {mod}: {activity.name}",
                    )
                    continue

                if mod == "resource" or mod == "pluginfile":
                    try:
                        response = self.fetch(
                            activity.url,
                            resource_name=activity.name,
                        )
                        if not html_response(response):
                            self.save_response_file(
                                response,
                                bucket_dir,
                                activity.name,
                                activity.url,
                                context,
                                prefix=section_prefix,
                            )
                        else:
                            response.close()
                            self.crawl_moodle_link(
                                activity.url,
                                bucket_dir,
                                activity.name,
                                depth + 1,
                                context,
                                activity_prefix,
                            )
                    except SyncCancelled:
                        raise
                    except AuthenticationError:
                        raise
                    except Exception as exc:
                        print(f"    [ERR] {exc}")
                        self.stats["errors"] += 1
                        self.log(
                            status="error",
                            context=activity.name,
                            source=activity.url,
                            error=str(exc),
                        )
                    continue

                try:
                    self.crawl_moodle_link(
                        activity.url,
                        bucket_dir,
                        activity.name,
                        depth + 1,
                        context,
                        activity_prefix,
                    )
                except SyncCancelled:
                    raise
                except AuthenticationError:
                    raise
                except Exception as exc:
                    self.stats["errors"] += 1
                    self.log(
                        status="error",
                        context=activity.name,
                        source=activity.url,
                        error=str(exc),
                    )

        if depth == 0:
            meta_dir = self._meta_dir()
            write_json(
                meta_dir / "course_structure.json",
                {
                    "root_course": course_name,
                    "root_course_url": course_url,
                    "courses": self.course_structures,
                },
            )
            write_json(
                meta_dir / "download_manifest.json",
                self.manifest,
            )
            write_json(meta_dir / "stats.json", self.stats)

            print("\n" + "#" * 78)
            print("HOÀN TẤT COURSE")
            print(f"Files tải mới : {self.stats['downloaded']}")
            print(f"Files skip     : {self.stats['skipped']}")
            print(
                f"Video bỏ qua  : {self.stats['skipped_video']} "
                "(video không được hỗ trợ)"
            )
            print(f"Pages lưu      : {self.stats['pages_saved']}")
            print(f"Errors         : {self.stats['errors']}")
            print(f"Output         : {course_dir}")
            print("#" * 78)

            self.emit(
                "course_complete",
                "Hoàn tất course",
                output=str(course_dir),
                stats=dict(self.stats),
            )

        return course_dir
