from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import DEEP_MODS, INTERACTIVE_MODS, REQUEST_TIMEOUT
from .models import Section
from .parser import choose_content_root, extract_section_content, parse_sections, sanitize_content_html
from .utils import (
    activity_type, clean_text, filename_from_response, html_response,
    is_course_url, is_probably_file_url, is_same_lms, is_video_response,
    is_video_url, normalize_url, safe_name, write_json, write_url_shortcut,
)

EventCallback = Callable[[dict], None]

class DeepDownloader:
    def __init__(
        self,
        session: requests.Session,
        output: Path,
        force: bool = False,
        max_depth: int = 4,
        follow_linked_courses: bool = True,
        download_video: bool = False,
        archive_mode: bool = False,
        event_callback: Optional[EventCallback] = None,
    ):
        self.session = session
        self.output = output
        self.force = force
        self.max_depth = max_depth
        self.follow_linked_courses = follow_linked_courses
        self.download_video = download_video
        self.archive_mode = archive_mode
        self.event_callback = event_callback
        self.visited: set[str] = set()
        self.course_visited: set[str] = set()
        self.manifest: list[dict] = []
        self.stats = {
            "downloaded": 0,
            "skipped": 0,
            "skipped_video": 0,
            "pages_saved": 0,
            "shortcuts": 0,
            "errors": 0,
        }

    def emit(self, event: str, message: str = "", **payload) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback({"event": event, "message": message, **payload})
        except Exception:
            # GUI/progress callback must never break a download.
            pass

    def log(self, **record) -> None:
        self.manifest.append(record)
        if record.get("status") == "error":
            detail = record.get("error") or record.get("source") or "Unknown error"
            self.emit("error", f"Lỗi: {detail}", **record)

    def fetch(self, url: str, stream: bool = True) -> requests.Response:
        r = self.session.get(
            url, stream=stream, allow_redirects=True, timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        return r

    def save_response_file(
        self,
        response: requests.Response,
        dest_dir: Path,
        fallback: str,
        source: str,
        context: str,
        prefix: str = "",
    ) -> Optional[Path]:
        if not self.download_video and is_video_response(response):
            self.stats["skipped_video"] += 1
            self.log(status="skipped_video", context=context, source=source, final_url=response.url)
            self.emit("video_skipped", f"Bỏ qua video: {fallback}", source=source)
            print(f"    [VIDEO OFF] {fallback}")
            response.close()
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = filename_from_response(response, fallback)
        if prefix:
            filename = safe_name(prefix + filename, 190)
        target = dest_dir / filename

        remote_size_raw = response.headers.get("Content-Length", "")
        remote_size = int(remote_size_raw) if remote_size_raw.isdigit() else None

        if target.exists() and not self.force:
            if remote_size is None or target.stat().st_size == remote_size:
                print(f"    [SKIP] {target.name}")
                self.stats["skipped"] += 1
                self.log(status="skipped", context=context, source=source, path=str(target))
                self.emit("file_skipped", f"Đã có: {target.name}", path=str(target))
                return target

        temp = target.with_suffix(target.suffix + ".part")
        try:
            with temp.open("wb") as f:
                for chunk in response.iter_content(256 * 1024):
                    if chunk:
                        f.write(chunk)

            if target.exists():
                target.unlink()
            temp.replace(target)

            print(f"    [OK]   {target.name}")
            self.stats["downloaded"] += 1
            size = target.stat().st_size
            self.log(
                status="downloaded", context=context, source=source,
                final_url=response.url, path=str(target), size=size
            )
            self.emit("file_downloaded", f"Đã tải: {target.name}", path=str(target), size=size)
            return target

        except Exception as exc:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass
            self.stats["errors"] += 1
            self.log(status="error", context=context, source=source, error=str(exc))
            raise

    def save_shortcut(self, dest_dir: Path, name: str, url: str, context: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / (safe_name(name, 150) + ".url")
        if path.exists() and not self.force:
            return path
        write_url_shortcut(path, url)
        print(f"    [LINK] {path.name} -> {url}")
        self.stats["shortcuts"] += 1
        self.log(status="shortcut", context=context, source=url, path=str(path))
        return path

    def download_media_links(
        self,
        media_links: Iterable[tuple[str, str]],
        dest_dir: Path,
        context: str,
    ) -> None:
        seen = set()
        for label, url in media_links:
            url = normalize_url(url)
            if url in seen:
                continue
            seen.add(url)

            if not self.download_video and is_video_url(url):
                self.stats["skipped_video"] += 1
                self.log(status="skipped_video", context=context, source=url)
                self.emit("video_skipped", f"Bỏ qua video: {label or url}", source=url)
                print(f"    [VIDEO OFF] {label or url}")
                continue

            try:
                r = self.fetch(url)
                if html_response(r):
                    # Link tưởng file nhưng server trả HTML -> không ghi nhầm .pdf/.jpg.
                    print(f"    [INFO] Media trả HTML, bỏ qua: {url}")
                    continue
                self.save_response_file(r, dest_dir, label or "asset", url, context)
            except Exception as exc:
                print(f"    [ERR] asset {url}: {exc}")
                self.stats["errors"] += 1
                self.log(status="error", context=context, source=url, error=str(exc))

    def save_html_page(
        self,
        html: str,
        page_url: str,
        dest_dir: Path,
        title: str,
        context: str,
    ) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        root = choose_content_root(soup)
        html_doc, media_links, content_links = sanitize_content_html(root, page_url)

        dest_dir.mkdir(parents=True, exist_ok=True)
        text = clean_text(BeautifulSoup(html_doc, "html.parser").get_text("\n", strip=True))
        text_path = dest_dir / "content.txt"
        if text:
            text_path.write_text(text + "\n", encoding="utf-8")
        elif not self.archive_mode:
            text_path.write_text(f"Nguồn: {page_url}\n", encoding="utf-8")

        if self.archive_mode:
            html_path = dest_dir / "content.html"
            html_path.write_text(html_doc, encoding="utf-8")
            saved_path = html_path
        else:
            saved_path = text_path

        self.stats["pages_saved"] += 1
        self.log(status="page_saved", context=context, source=page_url, path=str(saved_path))
        self.emit("page_saved", f"Đã lưu nội dung: {title}", path=str(saved_path))
        print(f"    [PAGE] {saved_path.name}")

        if media_links:
            self.download_media_links(media_links, dest_dir / "assets", context)

        # Complete archive keeps external web shortcuts; Standard mode stays clean.
        if self.archive_mode:
            external = [u for u in content_links if not is_same_lms(u)]
            if external:
                ext_dir = dest_dir / "external_links"
                for idx, url in enumerate(external, start=1):
                    label = Path(unquote(urlparse(url).path)).name or urlparse(url).netloc or f"link_{idx}"
                    self.save_shortcut(ext_dir, f"{idx:02d}_{label}", url, context)

        return [u for u in content_links if is_same_lms(u)]

    def crawl_moodle_link(
        self,
        url: str,
        dest_dir: Path,
        title: str,
        depth: int,
        context: str,
    ) -> None:
        url = normalize_url(url)
        if depth > self.max_depth:
            print(f"    [DEPTH] Bỏ qua vì vượt max-depth: {url}")
            self.log(status="max_depth", context=context, source=url)
            return

        # Course xử lý riêng vì cần parse section tree.
        if is_course_url(url):
            if not self.follow_linked_courses:
                self.save_shortcut(dest_dir, title, url, context)
                return
            self.crawl_course(url, dest_dir, depth, linked_title=title)
            return

        normalized = normalize_url(url)
        if normalized in self.visited:
            print(f"    [VISITED] {url}")
            return
        self.visited.add(normalized)

        mod = activity_type(url)
        if mod in INTERACTIVE_MODS:
            if self.archive_mode:
                self.save_shortcut(dest_dir, title, url, context)
            else:
                self.emit("interactive_skipped", f"Bỏ qua {mod}: {title}")
            return

        try:
            r = self.fetch(url)
        except Exception as exc:
            print(f"    [ERR] {url}: {exc}")
            self.stats["errors"] += 1
            self.log(status="error", context=context, source=url, error=str(exc))
            return

        final_url = normalize_url(r.url)

        # Redirect sang course khác, ví dụ activity URL -> course video.
        if is_course_url(final_url):
            if self.follow_linked_courses:
                self.crawl_course(final_url, dest_dir, depth, linked_title=title)
            else:
                self.save_shortcut(dest_dir, title, final_url, context)
            return

        if not html_response(r):
            self.save_response_file(r, dest_dir, title, url, context)
            return

        # Redirect ra web ngoài -> lưu shortcut, không crawl toàn internet.
        if not is_same_lms(final_url):
            self.save_shortcut(dest_dir, title, final_url, context)
            return

        # Moodle HTML page: lưu nội dung + assets + theo links trong content.
        page_dir = dest_dir
        page_dir.mkdir(parents=True, exist_ok=True)
        try:
            html = r.content.decode(r.encoding or "utf-8", errors="replace")
        except Exception:
            html = r.text

        nested_links = self.save_html_page(html, final_url, page_dir, title, context)

        # Book: chapter links thường nằm ngoài generalbox/content chính.
        if mod == "book":
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select("a[href*='/mod/book/view.php']"):
                href = a.get("href")
                if href:
                    nested_links.append(normalize_url(urljoin(final_url, href)))

        # Crawl các Moodle links hợp lệ ở bên trong nội dung.
        filtered = []
        seen = set()
        for link in nested_links:
            link = normalize_url(link)
            if link in seen or link == final_url:
                continue
            seen.add(link)

            typ = activity_type(link)
            if typ == "pluginfile" or is_probably_file_url(link):
                filtered.append(link)
            elif typ in DEEP_MODS or typ == "course":
                filtered.append(link)
            elif typ in INTERACTIVE_MODS:
                if self.archive_mode:
                    link_name = Path(urlparse(link).path).parts[-2] if len(Path(urlparse(link).path).parts) >= 2 else typ
                    self.save_shortcut(page_dir / "links", link_name, link, context)

        for idx, link in enumerate(filtered, start=1):
            typ = activity_type(link)
            if typ == "pluginfile" or is_probably_file_url(link):
                try:
                    fr = self.fetch(link)
                    if not html_response(fr):
                        self.save_response_file(fr, page_dir / "linked_files", f"linked_{idx}", link, context)
                except Exception as exc:
                    print(f"    [ERR] nested file {link}: {exc}")
                continue

            nested_name = self.link_title(link) or f"nested_{idx}_{typ}"
            nested_dir = page_dir / "nested" / f"{idx:02d}_{safe_name(nested_name, 100)}"
            print(f"    -> đi sâu [{typ}] {nested_name}")
            self.crawl_moodle_link(link, nested_dir, nested_name, depth + 1, context)

    def link_title(self, url: str) -> Optional[str]:
        """GET nhẹ một HTML URL để lấy title. Fail thì None."""
        try:
            r = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if not html_response(r):
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            for selector in (".page-header-headings h1", "#region-main h2", "h1", "h2", "title"):
                node = soup.select_one(selector)
                if node:
                    text = clean_text(node.get_text(" ", strip=True))
                    text = re.sub(r"\s*\|\s*BK-LMS\s*$", "", text, flags=re.I)
                    if text:
                        return text
        except Exception:
            return None
        return None

    def save_section_inline_content(self, section: Section, section_dir: Path, course_url: str) -> None:
        html_doc, media_links, content_links = extract_section_content(section.node_html, course_url)
        if not html_doc:
            return

        content_dir = section_dir / "_inline_content"
        content_dir.mkdir(parents=True, exist_ok=True)
        if self.archive_mode:
            (content_dir / "content.html").write_text(html_doc, encoding="utf-8")
        text = clean_text(BeautifulSoup(html_doc, "html.parser").get_text("\n", strip=True))
        if text:
            (content_dir / "content.txt").write_text(text + "\n", encoding="utf-8")
        self.stats["pages_saved"] += 1
        print("  [INLINE] Đã lưu nội dung/ảnh nằm trực tiếp trong section")

        if media_links:
            self.download_media_links(media_links, content_dir / "assets", f"section:{section.title}")

        # Chỉ lưu shortcut cho external inline link; activity links đã parse riêng.
        if self.archive_mode:
            external = [u for u in content_links if not is_same_lms(u)]
            if external:
                for idx, url in enumerate(external, start=1):
                    self.save_shortcut(content_dir / "external_links", f"{idx:02d}_link", url, f"section:{section.title}")

    def crawl_course(
        self,
        course_url: str,
        parent_dir: Path,
        depth: int = 0,
        linked_title: Optional[str] = None,
    ) -> Optional[Path]:
        course_url = normalize_url(course_url)
        course_key = course_url

        # Một course có thể xuất hiện qua nhiều link; không crawl hai lần trong cùng run.
        if course_key in self.course_visited:
            print(f"  [COURSE VISITED] {course_url}")
            if linked_title:
                self.save_shortcut(parent_dir, linked_title + " (đã crawl ở nơi khác)", course_url, "course")
            return None
        self.course_visited.add(course_key)

        self.emit("course_start", f"Đang quét course: {course_url}", url=course_url, depth=depth)
        print("\n" + "#" * 78)
        print(f"CRAWL COURSE depth={depth}: {course_url}")
        print("#" * 78)

        try:
            page = self.session.get(course_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            page.raise_for_status()
        except Exception as exc:
            print(f"[ERR] Không mở được course: {exc}")
            self.stats["errors"] += 1
            self.log(status="error", context="course", source=course_url, error=str(exc))
            return None

        final_path = urlparse(page.url).path.lower()
        if "/login/" in final_path:
            message = "Phiên đăng nhập BK-LMS chưa hợp lệ hoặc đã hết hạn. Hãy đăng nhập lại trong Chrome."
            self.stats["errors"] += 1
            self.log(status="error", context="course", source=course_url, error=message)
            if depth == 0:
                raise RuntimeError(message)
            return None

        if not html_response(page):
            message = "Course URL không trả về trang HTML của BK-LMS."
            self.stats["errors"] += 1
            self.log(status="error", context="course", source=course_url, error=message)
            if depth == 0:
                raise RuntimeError(message)
            return None

        course_name, sections = parse_sections(page.text, page.url)

        if depth == 0:
            course_dir = parent_dir / safe_name(course_name, 150)
        else:
            # Với linked course, giữ activity folder, bên trong thêm tên course thực.
            course_dir = parent_dir / ("COURSE_" + safe_name(course_name, 145))

        course_dir.mkdir(parents=True, exist_ok=True)
        print(f"Tên course: {course_name}")
        print(f"Sections:   {len(sections)}")
        print(f"Output:     {course_dir}")

        structure = {
            "course_name": course_name,
            "course_url": course_url,
            "depth": depth,
            "sections": [
                {
                    "index": s.index,
                    "title": s.title,
                    "activities": [
                        {"order": a.order, "name": a.name, "url": a.url, "type": a.mod_type}
                        for a in s.activities
                    ],
                }
                for s in sections
            ],
        }
        write_json(course_dir / "_course_structure.json", structure)

        for section in sections:
            section_dir = course_dir / f"{section.index:02d}_{safe_name(section.title, 115)}"
            section_dir.mkdir(parents=True, exist_ok=True)

            self.emit(
                "section_start", f"{section.index:02d}. {section.title}",
                section_index=section.index, section_title=section.title,
                activity_count=len(section.activities),
            )
            print("\n" + "=" * 78)
            print(f"{section.index:02d}. {section.title} ({len(section.activities)} activity)")
            print("=" * 78)

            # Quan trọng: nội dung nằm trực tiếp trên course page, ví dụ Chapter 2
            # có text/ảnh nhưng không có activity link.
            self.save_section_inline_content(section, section_dir, course_url)

            for activity in section.activities:
                activity_prefix = f"{activity.order:02d}_"
                mod = activity.mod_type
                activity_label = safe_name(activity.name, 115)

                print(f"\n  [{mod}] {activity.name}")

                # Resource: muốn file ở ngay section, có prefix giữ đúng order.
                if mod == "resource" or mod == "pluginfile":
                    try:
                        r = self.fetch(activity.url)
                        if not html_response(r):
                            self.save_response_file(
                                r, section_dir, activity.name, activity.url,
                                f"{course_name} > {section.title} > {activity.name}",
                                prefix=activity_prefix,
                            )
                        else:
                            # resource hiếm khi trả landing HTML; xử lý deep như page.
                            activity_dir = section_dir / f"{activity.order:02d}_{activity_label}"
                            self.crawl_moodle_link(
                                activity.url, activity_dir, activity.name, depth + 1,
                                f"{course_name} > {section.title} > {activity.name}"
                            )
                    except Exception as exc:
                        print(f"    [ERR] {exc}")
                        self.stats["errors"] += 1
                        self.log(status="error", context=activity.name, source=activity.url, error=str(exc))
                    continue

                activity_dir = section_dir / f"{activity.order:02d}_{activity_label}"

                if mod in INTERACTIVE_MODS:
                    if self.archive_mode:
                        activity_dir.mkdir(parents=True, exist_ok=True)
                        self.save_shortcut(activity_dir, activity.name, activity.url, activity.name)
                    else:
                        self.emit("interactive_skipped", f"Bỏ qua {mod}: {activity.name}")
                    continue

                activity_dir.mkdir(parents=True, exist_ok=True)
                self.crawl_moodle_link(
                    activity.url,
                    activity_dir,
                    activity.name,
                    depth + 1,
                    f"{course_name} > {section.title} > {activity.name}",
                )

        write_json(course_dir / "_download_manifest.json", self.manifest)
        write_json(course_dir / "_stats.json", self.stats)

        print("\n" + "#" * 78)
        print("HOÀN TẤT COURSE")
        print(f"Files tải mới : {self.stats['downloaded']}")
        print(f"Files skip    : {self.stats['skipped']}")
        print(f"Video bỏ qua : {self.stats['skipped_video']}")
        print(f"Pages lưu     : {self.stats['pages_saved']}")
        print(f"Shortcuts     : {self.stats['shortcuts']}")
        print(f"Errors        : {self.stats['errors']}")
        print(f"Output        : {course_dir}")
        print("#" * 78)
        self.emit(
            "course_complete", "Hoàn tất course", output=str(course_dir),
            stats=dict(self.stats),
        )

        return course_dir


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

