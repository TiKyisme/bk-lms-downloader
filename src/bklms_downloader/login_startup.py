"""Worker-only Chrome startup with safe, numeric timing diagnostics."""

import threading
import time
import json
from collections.abc import Callable

from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchWindowException, TimeoutException,
)

from .app_logging import get_logger
from .auth import create_driver
from .config import LMS_BASE

LOG = get_logger(__name__)


def launch_error(exc: Exception, phase: str) -> str:
    if isinstance(exc, TimeoutException):
        return "Quá thời gian chờ BK-LMS. Chrome vẫn có thể dùng để đăng nhập."
    if isinstance(exc, (NoSuchWindowException, InvalidSessionIdException)):
        return "Cửa sổ Chrome đã đóng. Hãy mở Chrome lại."
    # Inspect only to classify; never copy driver stderr/URLs into the GUI/log.
    detail = str(exc).lower()
    if "cannot find chrome binary" in detail or "chrome not found" in detail:
        return "Không tìm thấy Google Chrome. Hãy cài Chrome rồi thử lại."
    if phase == "navigation":
        return "Không mở được trang BK-LMS. Kiểm tra kết nối hoặc thử lại trong Chrome."
    return "Không khởi động được Chrome/ChromeDriver. Kiểm tra Chrome và kết nối rồi thử lại."


class LoginStartup:
    """Serializes startup/reuse and shutdown of the app-owned driver only."""

    def __init__(self):
        self.driver = None
        self.closing = threading.Event()
        self.lock = threading.Lock()

    def run(self, emit: Callable[[dict], None], clicked_at: float) -> None:
        with self.lock:
            phase = "driver"
            def timing(name, seconds):
                LOG.info("Chrome startup timing %s=%.3fs", name, seconds)

            timing("worker_start", time.perf_counter() - clicked_at)
            try:
                if self.closing.is_set():
                    return
                if self.driver is not None:
                    try:
                        handles = self.driver.window_handles
                        if not handles:
                            raise NoSuchWindowException()
                        self.driver.switch_to.window(handles[0])
                    except Exception:
                        self._quit()
                if self.driver is None:
                    self.driver = create_driver(timing=timing)
                if self.closing.is_set():
                    return
                if not self.driver.window_handles:
                    raise NoSuchWindowException()
                timing("browser_ready", time.perf_counter() - clicked_at)
                emit({"event": "login_ready", "clicked_at": clicked_at})
                phase = "navigation"
                started = time.perf_counter()
                try:
                    self.driver.get(LMS_BASE)
                finally:
                    timing("navigation", time.perf_counter() - started)
                # eager navigation already waits for DOMContentLoaded. Import
                # and sync keep their own explicit readiness checks.
                timing("ready_wait", 0.0)
                emit({"event": "login_navigation_complete"})
            except Exception as exc:
                LOG.warning("Chrome startup failed phase=%s type=%s", phase, type(exc).__name__)
                if phase == "driver":
                    self._quit()
                emit({"event": "login_error", "message": launch_error(exc, phase)})
            finally:
                timing("total", time.perf_counter() - clicked_at)
                if self.closing.is_set():
                    self._quit()
                emit({"event": "login_finished"})

    def _quit(self):
        driver, self.driver = self.driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                LOG.warning("Chrome cleanup failed (owned driver)")

    def close(self):
        self.closing.set()
        with self.lock:
            self._quit()


def diagnose_chrome() -> int:
    """Explicit diagnostic: opens a fresh browser, times startup, then closes it."""
    startup = LoginStartup()
    started = time.perf_counter()
    results = {}

    def emit(event):
        results[event["event"]] = round(time.perf_counter() - started, 3)

    try:
        startup.run(emit, started)
        print(json.dumps(results))
        return 1 if "login_error" in results else 0
    finally:
        startup.close()
