from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import requests

from .course_store import CourseStore
from .crawler import DeepDownloader
from .models import Course, CourseSyncResult, SyncBatchResult
from .utils import extract_course_code


EventCallback = Callable[[dict[str, Any]], None]
DownloaderFactory = Callable[..., DeepDownloader]


class SyncManager:
    """Sequentially synchronize saved courses through one in-memory session."""

    def __init__(
        self,
        store: CourseStore | None = None,
        downloader_factory: DownloaderFactory = DeepDownloader,
        *,
        force: bool = False,
        max_depth: int = 4,
        follow_linked_courses: bool = True,
    ):
        self.store = store
        self.downloader_factory = downloader_factory
        self.force = force
        self.max_depth = max_depth
        self.follow_linked_courses = follow_linked_courses

    def sync_courses(
        self,
        courses: Iterable[Course],
        session: requests.Session,
        event_callback: EventCallback | None = None,
    ) -> SyncBatchResult:
        course_list = list(courses)
        results: list[CourseSyncResult] = []
        authentication_error = False

        for index, course in enumerate(course_list, start=1):
            self._emit(
                event_callback,
                "course_sync_start",
                course=course,
                index=index,
                total=len(course_list),
            )
            result = self.sync_course(course, session, event_callback)
            results.append(result)
            if self.store is not None:
                self.store.update_sync(course.id, result)
            self._emit(
                event_callback,
                "course_sync_complete",
                course=course,
                result=result,
                index=index,
                total=len(course_list),
            )

            if self._is_authentication_error(result):
                authentication_error = True
                break

        batch = SyncBatchResult(results, authentication_error=authentication_error)
        self._emit(
            event_callback,
            "sync_all_complete",
            result=batch,
            total=len(course_list),
        )
        return batch

    def sync_course(
        self,
        course: Course,
        session: requests.Session,
        event_callback: EventCallback | None = None,
    ) -> CourseSyncResult:
        def crawler_event(event: dict[str, Any]) -> None:
            self._emit(event_callback, "crawler_event", course=course, activity=event)

        downloader = self.downloader_factory(
            session=session,
            output=course.output_path,
            force=self.force,
            max_depth=self.max_depth,
            follow_linked_courses=self.follow_linked_courses,
            event_callback=crawler_event,
        )
        try:
            output = downloader.crawl_course(course.url, course.output_path, depth=0)
            stats = dict(downloader.stats)
            name = getattr(downloader, "root_course_name", None) or course.display_name
            if output is None:
                message = "Không thể đồng bộ course này."
                return self._result(course, name, None, stats, "error", message)
            status = "error" if stats.get("errors", 0) else (
                "success" if stats.get("downloaded", 0) else "up_to_date"
            )
            return self._result(course, name, Path(output), stats, status)
        except Exception as exc:
            stats = dict(getattr(downloader, "stats", {}))
            stats["errors"] = max(1, int(stats.get("errors", 0)))
            return self._result(
                course,
                course.display_name,
                None,
                stats,
                "error",
                str(exc),
            )

    @staticmethod
    def _result(
        course: Course,
        name: str,
        output: Path | None,
        stats: dict[str, int],
        status: str,
        error_message: str | None = None,
    ) -> CourseSyncResult:
        return CourseSyncResult(
            course_id=course.id,
            course_url=course.url,
            name=name,
            output=output,
            downloaded=int(stats.get("downloaded", 0)),
            skipped=int(stats.get("skipped", 0)),
            skipped_video=int(stats.get("skipped_video", 0)),
            pages_saved=int(stats.get("pages_saved", 0)),
            errors=int(stats.get("errors", 0)),
            status=status,
            error_message=error_message,
        )

    @staticmethod
    def _is_authentication_error(result: CourseSyncResult) -> bool:
        message = (result.error_message or "").lower()
        return "phiên đăng nhập" in message or "đăng nhập lại" in message

    @staticmethod
    def _emit(
        callback: EventCallback | None,
        event: str,
        **payload: Any,
    ) -> None:
        if callback is None:
            return
        try:
            callback({"event": event, **payload})
        except Exception:
            pass
