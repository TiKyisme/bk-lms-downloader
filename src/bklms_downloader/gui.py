from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import __version__
from .ai_prepare import AICoursePreparer, OptionalAIDependenciesError, default_ai_output
from .app_settings import AppSettings
from .app_logging import get_logger
from .auth import create_driver, make_session, wait_page
from .config import LMS_BASE
from .course_discovery import (
    CourseDiscoveryError,
    DiscoveredCourse,
    SessionExpiredError,
    discover_courses,
)
from .course_store import CourseStore
from .models import Course, SyncBatchResult
from .sync_manager import SyncManager
from .update_checker import UpdateChecker, UpdateInfo
from .utils import is_course_url, safe_name


LOG = get_logger(__name__)


class CourseDialog(tk.Toplevel):
    """The intentionally small dialog used for adding and editing a course."""

    def __init__(
        self,
        parent: "App",
        course: Course | None,
        on_save: Callable[[str, str, str], None],
    ):
        super().__init__(parent)
        self.app = parent
        self.on_save = on_save
        self.title("Sửa course" if course else "Thêm course")
        self.resizable(True, False)
        self.transient(parent)
        self.grab_set()

        self.url_var = tk.StringVar(value=course.url if course else "")
        self.name_var = tk.StringVar(value=course.name if course else "")
        self.output_var = tk.StringVar(
            value=course.output if course else parent.settings.last_output_dir
        )
        self._build()
        self.after(20, self.url_entry.focus_set)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="URL course BK-LMS").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.url_entry = ttk.Entry(frame, textvariable=self.url_var, width=64)
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(
            frame,
            text="Dùng course đang mở",
            command=self._use_current_course,
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))
        ttk.Label(
            frame,
            text="Ví dụ: https://lms.hcmut.edu.vn/course/view.php?id=123456",
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Label(frame, text="Tên hiển thị (tuỳ chọn)").grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Entry(frame, textvariable=self.name_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Thư mục lưu").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=3, column=1, sticky="ew"
        )
        ttk.Button(frame, text="Chọn folder...", command=self._choose_output).grid(
            row=3, column=2, padx=(8, 0)
        )

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(actions, text="Hủy", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Lưu", command=self._submit).pack(
            side="right", padx=(0, 8)
        )

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(
            parent=self,
            initialdir=self.output_var.get() or str(Path.home()),
        )
        if not path:
            return
        self.output_var.set(path)
        try:
            self.app.settings.set_last_output_dir(path)
        except OSError as exc:
            LOG.warning("Could not remember output folder: %s", exc)
            messagebox.showerror("Không thể nhớ thư mục", str(exc), parent=self)

    def _use_current_course(self) -> None:
        url = self.app.current_course_url()
        if url:
            self.url_var.set(url)

    def _submit(self) -> None:
        url = self.url_var.get().strip()
        output = self.output_var.get().strip()
        if not is_course_url(url):
            messagebox.showwarning("Course URL", "URL course BK-LMS không hợp lệ.", parent=self)
            return
        if not output:
            messagebox.showwarning("Thư mục lưu", "Hãy chọn thư mục để lưu tài liệu.", parent=self)
            return
        try:
            self.on_save(url, self.name_var.get().strip(), output)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Không thể lưu course", str(exc), parent=self)
            return
        self.destroy()


class ImportCoursesDialog(tk.Toplevel):
    """Let students explicitly choose which discovered courses to save."""

    def __init__(
        self,
        parent: "App",
        courses: list[DiscoveredCourse],
        on_add: Callable[[list[DiscoveredCourse]], None],
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.courses = courses
        self.on_add = on_add
        self.selected_urls: set[str] = set()
        self.available_urls = {
            course.url for course in courses if not parent.course_exists(course.url)
        }
        self.title("Nhập course từ BK-LMS")
        self.geometry("650x420")
        self.minsize(560, 330)
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text="Chọn course muốn thêm. Course đã có sẽ không bị thêm lại.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.tree = ttk.Treeview(
            frame,
            columns=("selected", "code", "name", "status"),
            show="headings",
            selectmode="browse",
        )
        for column, title, width in (
            ("selected", "Chọn", 55),
            ("code", "Mã môn", 80),
            ("name", "Tên môn", 330),
            ("status", "", 115),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w", stretch=column == "name")
        for index, course in enumerate(self.courses):
            available = course.url in self.available_urls
            if available:
                self.selected_urls.add(course.url)
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "☑" if available else "",
                    course.code or "-",
                    course.name,
                    "" if available else "Đã thêm",
                ),
            )
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._toggle_course)

        ttk.Label(
            frame,
            text=f"Thư mục lưu mặc định: {self.parent_app.settings.last_output_dir}",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Hủy", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Thêm đã chọn", command=self._submit).pack(
            side="right", padx=(0, 8)
        )

    def _toggle_course(self, event: tk.Event) -> str | None:
        if self.tree.identify_column(event.x) != "#1":
            return None
        item = self.tree.identify_row(event.y)
        if not item:
            return "break"
        course = self.courses[int(item)]
        if course.url not in self.available_urls:
            return "break"
        values = list(self.tree.item(item, "values"))
        if course.url in self.selected_urls:
            self.selected_urls.remove(course.url)
            values[0] = "☐"
        else:
            self.selected_urls.add(course.url)
            values[0] = "☑"
        self.tree.item(item, values=values)
        return "break"

    def _submit(self) -> None:
        selected = [course for course in self.courses if course.url in self.selected_urls]
        if not selected:
            messagebox.showwarning("Chưa chọn course", "Hãy chọn ít nhất một course để thêm.", parent=self)
            return
        self.on_add(selected)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"BK-LMS Downloader v{__version__}")
        self.geometry("900x660")
        self.minsize(760, 540)

        self.driver = None
        self.events: queue.Queue[dict] = queue.Queue()
        self.store = CourseStore()
        self.settings = AppSettings()
        self.syncing = False
        self.update_info: UpdateInfo | None = None

        self.login_status_var = tk.StringVar(value="Chưa đăng nhập")
        self.course_detail_var = tk.StringVar(value="Chọn course để xem thư mục lưu.")
        self.overall_var = tk.StringVar(value="Chưa có phiên đồng bộ")
        self.current_course_var = tk.StringVar(value="Sẵn sàng đồng bộ")
        self.summary_var = tk.StringVar(value="Chưa có kết quả đồng bộ.")

        self._build_ui()
        self._refresh_courses()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_events)
        self._check_for_updates()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text="BK-LMS Downloader", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        login = ttk.Frame(outer)
        login.grid(row=1, column=0, sticky="ew", pady=(10, 14))
        self.login_btn = ttk.Button(
            login, text="Mở Chrome để đăng nhập", command=self._open_login
        )
        self.login_btn.pack(side="left")
        ttk.Label(login, textvariable=self.login_status_var).pack(side="left", padx=12)
        self.update_notice = ttk.Frame(login)
        self.update_notice_var = tk.StringVar()
        ttk.Label(self.update_notice, textvariable=self.update_notice_var).pack(side="left")
        ttk.Button(
            self.update_notice,
            text="Xem cập nhật",
            command=self._open_update,
        ).pack(side="left", padx=(6, 0))
        ttk.Label(login, text="Ứng dụng không lưu mật khẩu/cookie.").pack(side="right")

        courses_panel = ttk.Labelframe(outer, text="Khóa học của tôi", padding=10)
        courses_panel.grid(row=2, column=0, sticky="nsew")
        self._build_courses_panel(courses_panel)

        sync_panel = ttk.Labelframe(outer, text="Đồng bộ", padding=10)
        sync_panel.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self._build_sync_panel(sync_panel)

        ttk.Label(
            outer,
            text="Video luôn được bỏ qua. Tài liệu được gom gọn theo nhóm để dễ tìm.",
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

    def _build_courses_panel(self, panel: ttk.LabelFrame) -> None:
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        columns = ("selected", "code", "name", "last_sync", "status")
        self.course_tree = ttk.Treeview(
            panel,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=10,
        )
        headings = {
            "selected": "Chọn",
            "code": "Mã môn",
            "name": "Tên môn",
            "last_sync": "Lần đồng bộ",
            "status": "Trạng thái",
        }
        widths = {
            "selected": 50,
            "code": 70,
            "name": 260,
            "last_sync": 110,
            "status": 135,
        }
        for column in columns:
            self.course_tree.heading(column, text=headings[column])
            self.course_tree.column(
                column,
                width=widths[column],
                minwidth=widths[column],
                anchor="w",
                stretch=column == "name",
            )
        self.course_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.course_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.course_tree.configure(yscrollcommand=scrollbar.set)
        self.course_tree.bind("<Button-1>", self._on_tree_click)
        self.course_tree.bind("<Double-1>", lambda _event: self._edit_course())
        self.course_tree.bind("<<TreeviewSelect>>", self._on_course_selected)

        ttk.Label(panel, textvariable=self.course_detail_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        controls = ttk.Frame(panel)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.add_btn = ttk.Button(controls, text="+ Thêm course", command=self._add_course)
        self.import_btn = ttk.Button(controls, text="Nhập từ BK-LMS", command=self._import_courses)
        self.edit_btn = ttk.Button(controls, text="Sửa", command=self._edit_course)
        self.delete_btn = ttk.Button(controls, text="Xóa", command=self._delete_course)
        self.open_btn = ttk.Button(controls, text="Mở thư mục", command=self._open_course_folder)
        self.tools_btn = ttk.Menubutton(controls, text="Công cụ")
        self.tools_menu = tk.Menu(self.tools_btn, tearoff=False)
        self.tools_menu.add_command(label="Chuẩn bị cho AI", command=self._prepare_for_ai)
        self.tools_btn.configure(menu=self.tools_menu)
        for button in (
            self.add_btn,
            self.import_btn,
            self.edit_btn,
            self.delete_btn,
            self.open_btn,
            self.tools_btn,
        ):
            button.pack(side="left", padx=(0, 6))

        sync_actions = ttk.Frame(panel)
        sync_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.sync_selected_btn = ttk.Button(
            sync_actions, text="Sync selected", command=lambda: self._start_sync(True)
        )
        self.sync_all_btn = ttk.Button(
            sync_actions, text="Sync all", command=lambda: self._start_sync(False)
        )
        self.sync_selected_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.sync_all_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_sync_panel(self, panel: ttk.LabelFrame) -> None:
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, textvariable=self.current_course_var).grid(row=0, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.overall_var).grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(panel, mode="determinate", maximum=1)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 8))
        ttk.Label(panel, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(panel, text="Hoạt động gần đây").grid(row=3, column=0, columnspan=2, sticky="w")
        self.log_text = tk.Text(panel, height=6, wrap="word", state="disabled")
        self.log_text.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _refresh_courses(self) -> None:
        selected = self.course_tree.focus() if hasattr(self, "course_tree") else ""
        for item in self.course_tree.get_children():
            self.course_tree.delete(item)
        for course in self.store.list():
            self.course_tree.insert(
                "",
                "end",
                iid=course.id,
                values=(
                    "☑" if course.selected else "☐",
                    course.code or "-",
                    course.display_name,
                    self._format_last_sync(course.last_sync),
                    self._status_text(course),
                ),
            )
        if selected and self.course_tree.exists(selected):
            self.course_tree.focus(selected)
            self.course_tree.selection_set(selected)
            self._show_course_detail(selected)
        elif not self.course_tree.get_children():
            self.course_detail_var.set("Chưa có course. Hãy thêm course đầu tiên của bạn.")

    @staticmethod
    def _format_last_sync(value: str | None) -> str:
        if not value:
            return "Chưa đồng bộ"
        try:
            return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
        except ValueError:
            return value

    @staticmethod
    def _status_text(course: Course) -> str:
        if course.last_status == "never":
            return "Chưa đồng bộ"
        if course.last_status == "success":
            return f"{course.last_downloaded} file mới" if course.last_downloaded else "Hoàn tất"
        if course.last_status == "up_to_date":
            return "Không có thay đổi"
        return f"{max(1, course.last_errors)} lỗi"

    def _on_tree_click(self, event: tk.Event) -> str | None:
        if self.syncing:
            return "break"
        if self.course_tree.identify_column(event.x) != "#1":
            return None
        item = self.course_tree.identify_row(event.y)
        course = self.store.get(item)
        if course is not None:
            self.store.edit(course.id, selected=not course.selected)
            self._refresh_courses()
        return "break"

    def _on_course_selected(self, _event: tk.Event) -> None:
        self._show_course_detail(self.course_tree.focus())

    def _show_course_detail(self, course_id: str) -> None:
        course = self.store.get(course_id)
        if course is not None:
            self.course_detail_var.set(f"Thư mục lưu: {course.output}")

    def _selected_course(self) -> Course | None:
        course = self.store.get(self.course_tree.focus())
        if course is None:
            messagebox.showwarning("Chọn course", "Hãy chọn một course trong danh sách.", parent=self)
        return course

    def _add_course(self) -> None:
        if self.syncing:
            return

        def save(url: str, name: str, output: str) -> None:
            self.settings.set_last_output_dir(output)
            self.store.add(url, output, name=name)
            self._refresh_courses()

        CourseDialog(self, None, save)

    def course_exists(self, url: str) -> bool:
        return any(course.url == url for course in self.store.list())

    def _import_courses(self) -> None:
        if self.syncing:
            return
        if self.driver is None:
            messagebox.showwarning(
                "Chưa đăng nhập",
                "Hãy mở Chrome và đăng nhập BK-LMS trước.",
                parent=self,
            )
            return
        self._set_busy(True)
        self.current_course_var.set("Đang đọc danh sách course từ BK-LMS...")
        self.summary_var.set("Bạn vẫn có thể thêm course bằng URL nếu cần.")

        def worker() -> None:
            try:
                wait_page(self.driver, extra=0.1)
                session = make_session(self.driver)
                courses = discover_courses(session)
                self.events.put({"event": "courses_discovered", "courses": courses})
            except (CourseDiscoveryError, SessionExpiredError) as exc:
                self.events.put({"event": "course_discovery_error", "error": str(exc)})
            except Exception:
                self.events.put(
                    {
                        "event": "course_discovery_error",
                        "error": "Không thể đọc danh sách môn học. Bạn vẫn có thể thêm course bằng URL.",
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_imported_courses(self, courses: list[DiscoveredCourse]) -> None:
        self._set_busy(False)
        self.current_course_var.set("Sẵn sàng đồng bộ")
        self.login_status_var.set("Đã đăng nhập BK-LMS")
        if not courses:
            self.summary_var.set("Không tìm thấy course nào để nhập.")
            messagebox.showinfo(
                "Nhập từ BK-LMS",
                "Không tìm thấy course nào. Bạn vẫn có thể thêm course bằng URL.",
                parent=self,
            )
            return

        def add_selected(selected: list[DiscoveredCourse]) -> None:
            for course in selected:
                try:
                    self.store.add(
                        course.url,
                        self.settings.last_output_dir,
                        name=course.name,
                        code=course.code,
                    )
                except ValueError:
                    continue
            self._refresh_courses()
            self.summary_var.set(f"Đã thêm {len(selected)} course. Sẵn sàng đồng bộ.")

        ImportCoursesDialog(self, courses, add_selected)

    def _edit_course(self) -> None:
        if self.syncing:
            return
        course = self._selected_course()
        if course is None:
            return

        def save(url: str, name: str, output: str) -> None:
            self.settings.set_last_output_dir(output)
            self.store.edit(course.id, url=url, name=name, output=output)
            self._refresh_courses()

        CourseDialog(self, course, save)

    def _delete_course(self) -> None:
        if self.syncing:
            return
        course = self._selected_course()
        if course is None:
            return
        confirmed = messagebox.askyesno(
            "Xóa course",
            f"Xóa '{course.display_name}' khỏi danh sách?\n\n"
            "Tài liệu đã tải trên ổ đĩa sẽ không bị xóa.",
            parent=self,
        )
        if confirmed:
            self.store.remove(course.id)
            self._refresh_courses()

    def _open_course_folder(self) -> None:
        course = self._selected_course()
        if course is None:
            return
        output = course.output_path
        named_output = output / safe_name(course.name, 150) if course.name else output
        path = named_output if named_output.exists() else output
        if not path.exists():
            messagebox.showwarning("Thư mục", "Chưa tìm thấy thư mục kết quả.", parent=self)
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif os.name == "posix":
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            LOG.warning("Could not open output folder: %s", exc)
            messagebox.showerror(
                "Mở thư mục",
                "Không thể mở thư mục đã chọn.",
                parent=self,
            )

    def _course_root(self, course: Course) -> Path:
        output = course.output_path
        named_output = output / safe_name(course.name, 150) if course.name else output
        return named_output if named_output.exists() else output

    def _prepare_for_ai(self) -> None:
        if self.syncing:
            return
        course = self._selected_course()
        if course is None:
            return
        course_root = self._course_root(course)
        destination = default_ai_output(course_root)
        if not course_root.exists():
            messagebox.showwarning(
                "Chuẩn bị cho AI",
                "Hãy đồng bộ course ít nhất một lần trước khi chuẩn bị cho AI.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Chuẩn bị cho AI",
            f"Tạo lại knowledge base tại:\n{destination}\n\n"
            "Tính năng này là tuỳ chọn và có thể mất vài phút.",
            parent=self,
        ):
            return

        self._set_busy(True)
        self.current_course_var.set(f"Đang chuẩn bị cho AI: {course.display_name}")
        self.summary_var.set("Đang xử lý tài liệu đã tải...")

        def worker() -> None:
            try:
                output = AICoursePreparer().prepare(course_root, destination)
                self.events.put({"event": "ai_prepare_complete", "output": output})
            except OptionalAIDependenciesError as exc:
                self.events.put({"event": "ai_prepare_missing", "error": str(exc)})
            except Exception:
                self.events.put(
                    {
                        "event": "ai_prepare_error",
                        "error": "Không thể chuẩn bị course cho AI. Hãy thử lại sau.",
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def _open_login(self) -> None:
        if self.syncing:
            return
        self.login_btn.configure(state="disabled")
        self.login_status_var.set("Đang mở Chrome...")

        def worker() -> None:
            try:
                if self.driver is None:
                    self.driver = create_driver()
                self.driver.get(LMS_BASE)
                wait_page(self.driver)
                self.events.put(
                    {
                        "event": "login_ready",
                        "message": "Chrome đã mở. Hãy đăng nhập BK-LMS trực tiếp trong Chrome.",
                    }
                )
            except Exception as exc:
                LOG.warning("Could not open Chrome: %s", exc)
                self.driver = None
                self.events.put({"event": "login_error"})

        threading.Thread(target=worker, daemon=True).start()

    def _check_for_updates(self) -> None:
        def worker() -> None:
            update = UpdateChecker(__version__).check()
            if update is not None:
                self.events.put({"event": "update_available", "update": update})

        threading.Thread(target=worker, daemon=True).start()

    def _open_update(self) -> None:
        if self.update_info is not None:
            webbrowser.open(self.update_info.release_url)

    def current_course_url(self) -> str | None:
        """Use the currently open Chrome course without creating a new mode."""
        if self.driver is None:
            messagebox.showwarning(
                "Chưa mở Chrome",
                "Hãy mở Chrome để đăng nhập trước.",
                parent=self,
            )
            return None
        try:
            url = self.driver.current_url
        except Exception as exc:
            LOG.warning("Could not read current Chrome URL: %s", exc)
            messagebox.showerror("Chrome", "Không thể đọc course đang mở trong Chrome.", parent=self)
            return None
        if not is_course_url(url):
            messagebox.showwarning(
                "Chưa ở trang course",
                "Hãy mở một course BK-LMS trong Chrome rồi thử lại.",
                parent=self,
            )
            return None
        self.login_status_var.set("Đã đăng nhập BK-LMS")
        return url

    def _start_sync(self, selected_only: bool) -> None:
        if self.driver is None:
            messagebox.showwarning(
                "Chưa đăng nhập",
                "Hãy bấm 'Mở Chrome để đăng nhập' và đăng nhập BK-LMS trước.",
                parent=self,
            )
            return
        courses = self.store.list()
        if selected_only:
            courses = [course for course in courses if course.selected]
        if not courses:
            messagebox.showwarning(
                "Chưa có course",
                "Hãy thêm course hoặc chọn ít nhất một course để đồng bộ.",
                parent=self,
            )
            return

        self._set_busy(True)
        self.progress.configure(maximum=len(courses), value=0)
        self.overall_var.set(f"0 / {len(courses)} course")
        self.current_course_var.set("Đang kiểm tra phiên đăng nhập...")
        self.summary_var.set("Đang đồng bộ...")
        self.login_status_var.set("Đang đồng bộ...")
        self._log("[SYNC] Bắt đầu đồng bộ các course đã chọn.")

        def worker() -> None:
            try:
                wait_page(self.driver, extra=0.1)
                session = make_session(self.driver)
                manager = SyncManager(self.store)
                manager.sync_courses(courses, session, self._emit_from_worker)
            except Exception as exc:
                LOG.warning("Sync worker failed: %s", exc)
                self.events.put({"event": "job_error"})

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self.syncing = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.login_btn,
            self.add_btn,
            self.import_btn,
            self.edit_btn,
            self.delete_btn,
            self.open_btn,
            self.tools_btn,
            self.sync_selected_btn,
            self.sync_all_btn,
        ):
            button.configure(state=state)

    def _emit_from_worker(self, event: dict) -> None:
        self.events.put(event)

    def _drain_events(self) -> None:
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self._drain_events)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "login_ready":
            self.login_status_var.set("Chrome đã mở — hãy đăng nhập")
            self.login_btn.configure(state="normal")
        elif kind == "login_error":
            self.login_status_var.set("Không mở được Chrome")
            self.login_btn.configure(state="normal")
            messagebox.showerror(
                "Không mở được Chrome",
                "Không thể mở Chrome. Hãy kiểm tra Chrome rồi thử lại.",
                parent=self,
            )
        elif kind == "courses_discovered":
            self._show_imported_courses(event["courses"])
        elif kind == "course_discovery_error":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            message = event["error"]
            self.summary_var.set(message)
            if "đăng nhập" in message.lower():
                self.login_status_var.set("Phiên đăng nhập hết hạn")
            messagebox.showwarning("Nhập từ BK-LMS", message, parent=self)
        elif kind == "ai_prepare_complete":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self.summary_var.set("Đã chuẩn bị course cho AI.")
            messagebox.showinfo(
                "Chuẩn bị cho AI",
                f"Đã tạo knowledge base tại:\n{event['output']}",
                parent=self,
            )
        elif kind == "ai_prepare_missing":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self.summary_var.set("Tính năng AI cần cài thêm gói tuỳ chọn.")
            messagebox.showinfo("Chuẩn bị cho AI", event["error"], parent=self)
        elif kind == "ai_prepare_error":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self.summary_var.set("Không thể chuẩn bị course cho AI.")
            messagebox.showwarning("Chuẩn bị cho AI", event["error"], parent=self)
        elif kind == "update_available":
            self.update_info = event["update"]
            self.update_notice_var.set(f"Có bản cập nhật v{self.update_info.latest_version}")
            self.update_notice.pack(side="left", padx=(4, 8))
        elif kind == "course_sync_start":
            course: Course = event["course"]
            index, total = event["index"], event["total"]
            self.overall_var.set(f"{index} / {total} course")
            self.current_course_var.set(f"Đang đồng bộ: {course.code or '-'} — {course.display_name}")
            self._set_tree_status(course.id, "Đang đồng bộ...")
            self._log(f"[SYNC] {course.code or '-'} - {course.display_name}")
        elif kind == "crawler_event":
            self._handle_crawler_event(event["activity"])
        elif kind == "course_sync_complete":
            result = event["result"]
            self.progress.configure(value=event["index"])
            self._refresh_courses()
            if result.status == "error":
                self._log(f"[ERROR] {result.name}: không thể đồng bộ.")
            else:
                suffix = "Không có thay đổi" if result.status == "up_to_date" else f"{result.downloaded} mới"
                self._log(f"[DONE] {result.name} — {suffix}, {result.skipped} giữ nguyên")
        elif kind == "sync_all_complete":
            self._complete_sync(event["result"], event.get("total", 0))
        elif kind == "job_error":
            self._set_busy(False)
            self.login_status_var.set("Có lỗi")
            self.summary_var.set("Không thể hoàn tất đồng bộ.")
            messagebox.showerror(
                "Lỗi đồng bộ",
                "Không thể hoàn tất đồng bộ. Hãy kiểm tra kết nối rồi thử lại.",
                parent=self,
            )

    def _handle_crawler_event(self, activity: dict) -> None:
        kind = activity.get("event")
        message = activity.get("message", "")
        prefixes = {
            "file_downloaded": "[OK]",
            "page_saved": "[OK]",
            "file_skipped": "[SKIP]",
            "error": "[ERROR]",
        }
        if message and kind in prefixes:
            self._log(f"{prefixes[kind]} {message}")

    def _complete_sync(self, batch: SyncBatchResult, total: int) -> None:
        self._set_busy(False)
        self.progress.configure(value=len(batch.results))
        self.overall_var.set(f"{len(batch.results)} / {total} course")
        self.summary_var.set(
            f"{batch.downloaded} file mới • {batch.skipped} giữ nguyên • {batch.errors} lỗi"
        )
        self._refresh_courses()

        if batch.authentication_error:
            self.login_status_var.set("Phiên đăng nhập hết hạn")
            messagebox.showwarning(
                "Phiên đăng nhập hết hạn",
                self.summary_var.get() + "\n\nHãy đăng nhập lại trong Chrome rồi thử lại.",
                parent=self,
            )
        else:
            self.login_status_var.set("Đã đăng nhập BK-LMS")
            messagebox.showinfo("Đồng bộ hoàn tất", self.summary_var.get(), parent=self)

    def _set_tree_status(self, course_id: str, status: str) -> None:
        if not self.course_tree.exists(course_id):
            return
        values = list(self.course_tree.item(course_id, "values"))
        if values:
            values[-1] = status
            self.course_tree.item(course_id, values=values)

    def _log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
