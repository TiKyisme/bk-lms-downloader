from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from . import __version__
from .ai_prepare import AICoursePreparer, OptionalAIDependenciesError, default_ai_output
from .app_logging import get_logger
from .app_settings import AppSettings
from .auth import create_driver, make_session, wait_page
from .config import LMS_BASE
from .course_discovery import (
    CourseDiscoveryError,
    DiscoveredCourse,
    SessionExpiredError,
    discover_courses_with_browser_fallback,
)
from .course_store import CourseStore
from .models import Course, SyncBatchResult
from .sync_manager import SyncManager
from .ui_icons import icon
from .ui_theme import THEME
from .update_checker import UpdateChecker, UpdateInfo
from .utils import is_course_url, safe_name


LOG = get_logger(__name__)


class CourseDialog(ctk.CTkToplevel):
    """A compact CustomTkinter dialog for adding or editing a saved course."""

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
        self.geometry("680x330")
        self.minsize(600, 300)
        self.configure(fg_color=THEME.bg)
        self.transient(parent)
        self.grab_set()

        self.url_var = tk.StringVar(value=course.url if course else "")
        self.name_var = tk.StringVar(value=course.name if course else "")
        self.output_var = tk.StringVar(
            value=course.output if course else parent.settings.last_output_dir
        )
        self._build()
        self.after(80, self.url_entry.focus_set)

    def _build(self) -> None:
        card = ctk.CTkFrame(
            self,
            fg_color=THEME.surface,
            border_color=THEME.border,
            border_width=1,
            corner_radius=THEME.radius,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text="URL course BK-LMS",
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.text,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        self.url_entry = ctk.CTkEntry(
            card,
            textvariable=self.url_var,
            height=38,
            corner_radius=9,
            border_color=THEME.border,
        )
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 18), pady=(18, 5))
        ctk.CTkButton(
            card,
            text="Dùng course đang mở",
            command=self._use_current_course,
            height=32,
            fg_color=THEME.primary_soft,
            hover_color="#DDEEFF",
            text_color=THEME.primary,
            corner_radius=9,
        ).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(0, 14))
        ctk.CTkLabel(
            card,
            text="Ví dụ: https://lms.hcmut.edu.vn/course/view.php?id=123456",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).grid(row=1, column=2, sticky="e", padx=(8, 18), pady=(0, 14))

        ctk.CTkLabel(
            card,
            text="Tên hiển thị (tuỳ chọn)",
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.text,
        ).grid(row=2, column=0, sticky="w", padx=18, pady=5)
        ctk.CTkEntry(
            card,
            textvariable=self.name_var,
            height=38,
            corner_radius=9,
            border_color=THEME.border,
        ).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(12, 18), pady=5)

        ctk.CTkLabel(
            card,
            text="Thư mục lưu",
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.text,
        ).grid(row=3, column=0, sticky="w", padx=18, pady=5)
        ctk.CTkEntry(
            card,
            textvariable=self.output_var,
            height=38,
            corner_radius=9,
            border_color=THEME.border,
        ).grid(row=3, column=1, sticky="ew", padx=(12, 8), pady=5)
        ctk.CTkButton(
            card,
            text="Chọn folder...",
            command=self._choose_output,
            height=38,
            fg_color=THEME.surface,
            hover_color=THEME.primary_soft,
            text_color=THEME.primary,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
        ).grid(row=3, column=2, sticky="e", padx=(0, 18), pady=5)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=4, column=0, columnspan=3, sticky="e", padx=18, pady=(18, 18))
        ctk.CTkButton(
            actions,
            text="Hủy",
            command=self.destroy,
            height=38,
            width=94,
            fg_color=THEME.surface,
            hover_color=THEME.inset,
            text_color=THEME.text,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
        ).pack(side="right")
        ctk.CTkButton(
            actions,
            text="Lưu",
            command=self._submit,
            height=38,
            width=94,
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=9,
        ).pack(side="right", padx=(0, 8))

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


class ImportCoursesDialog(ctk.CTkToplevel):
    """CustomTkinter course picker that still requires an explicit confirmation."""

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
        self.available_urls = {
            course.url for course in courses if not parent.course_exists(course.url)
        }
        self.selection_vars: dict[str, tk.BooleanVar] = {
            course.url: tk.BooleanVar(value=course.url in self.available_urls)
            for course in courses
        }
        self.title("Nhập course từ BK-LMS")
        self.geometry("720x520")
        self.minsize(610, 390)
        self.configure(fg_color=THEME.bg)
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        card = ctk.CTkFrame(
            self,
            fg_color=THEME.surface,
            border_color=THEME.border,
            border_width=1,
            corner_radius=THEME.radius,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            card,
            text="Chọn course muốn thêm",
            font=(THEME.font_family, 17, "bold"),
            text_color=THEME.text,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 2))
        ctk.CTkLabel(
            card,
            text="Course đã có trong danh sách sẽ không bị thêm lại.",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).grid(row=0, column=0, sticky="sw", padx=18, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(
            card,
            fg_color=THEME.inset,
            corner_radius=10,
            border_color=THEME.border,
            border_width=1,
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=18, pady=(28, 10))
        scroll.grid_columnconfigure(2, weight=1)
        for index, course in enumerate(self.courses):
            available = course.url in self.available_urls
            row = ctk.CTkFrame(scroll, fg_color=THEME.surface, corner_radius=9, height=46)
            row.grid(row=index, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(2, weight=1)
            checkbox = ctk.CTkCheckBox(
                row,
                text="",
                variable=self.selection_vars[course.url],
                onvalue=True,
                offvalue=False,
                width=28,
                checkbox_width=20,
                checkbox_height=20,
                fg_color=THEME.primary,
                hover_color=THEME.primary_hover,
                border_color=THEME.border,
            )
            checkbox.grid(row=0, column=0, padx=(12, 8), pady=11)
            if not available:
                checkbox.configure(state="disabled")
            ctk.CTkLabel(
                row,
                text=course.code or "-",
                width=80,
                anchor="w",
                font=(THEME.font_family, 13, "bold"),
                text_color=THEME.primary if course.code else THEME.muted_text,
            ).grid(row=0, column=1, sticky="w", padx=(0, 8))
            ctk.CTkLabel(
                row,
                text=course.name,
                anchor="w",
                font=(THEME.font_family, 14),
                text_color=THEME.text,
            ).grid(row=0, column=2, sticky="ew", padx=(0, 8))
            if not available:
                ctk.CTkLabel(
                    row,
                    text="Đã thêm",
                    font=(THEME.font_family, 12, "bold"),
                    text_color=THEME.muted_text,
                ).grid(row=0, column=3, sticky="e", padx=12)

        ctk.CTkLabel(
            card,
            text=f"Thư mục lưu mặc định: {self.parent_app.settings.last_output_dir}",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 8))
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="e", padx=18, pady=(0, 18))
        ctk.CTkButton(
            actions,
            text="Hủy",
            command=self.destroy,
            height=38,
            width=100,
            fg_color=THEME.surface,
            hover_color=THEME.inset,
            text_color=THEME.text,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
        ).pack(side="right")
        ctk.CTkButton(
            actions,
            text="Thêm đã chọn",
            command=self._submit,
            height=38,
            width=142,
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=9,
        ).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        selected = [
            course for course in self.courses if self.selection_vars[course.url].get()
        ]
        if not selected:
            messagebox.showwarning("Chưa chọn course", "Hãy chọn ít nhất một course để thêm.", parent=self)
            return
        self.on_add(selected)
        self.destroy()


class CourseRow(ctk.CTkFrame):
    """A reusable modern row for the CustomTkinter My Courses list."""

    def __init__(
        self,
        parent,
        course: Course,
        on_select: Callable[[str], None],
        on_toggle: Callable[[str, bool], None],
    ):
        super().__init__(parent, fg_color=THEME.surface, corner_radius=9, height=52)
        self.course = course
        self._on_select = on_select
        self._on_toggle = on_toggle
        self.grid_columnconfigure(2, weight=1)
        self.grid_propagate(False)

        self.check_var = tk.BooleanVar(value=course.selected)
        self.checkbox = ctk.CTkCheckBox(
            self,
            text="",
            variable=self.check_var,
            onvalue=True,
            offvalue=False,
            command=self._toggle,
            width=30,
            checkbox_width=21,
            checkbox_height=21,
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            border_color=THEME.border,
        )
        self.checkbox.grid(row=0, column=0, padx=(14, 8), pady=12, sticky="w")
        self.code_label = self._label(course.code or "-", 1, 90, "bold", THEME.primary if course.code else THEME.muted_text)
        self.name_label = self._label(course.display_name, 2, 0, "normal", THEME.text)
        self.last_sync_label = self._label(App._format_last_sync(course.last_sync), 3, 160, "normal", THEME.muted_text)
        status, color = App._status_text(course)
        self.status_label = self._label(status, 4, 145, "bold", color)
        for widget in (self, self.code_label, self.name_label, self.last_sync_label, self.status_label):
            widget.bind("<Button-1>", self._select)

    def _label(self, text: str, column: int, width: int, weight: str, color: str):
        label = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            width=width if width else 0,
            font=(THEME.font_family, 14, weight),
            text_color=color,
        )
        label.grid(row=0, column=column, sticky="ew" if column == 2 else "w", padx=(8, 8))
        return label

    def _toggle(self) -> None:
        self._on_toggle(self.course.id, bool(self.check_var.get()))

    def _select(self, _event=None) -> None:
        self._on_select(self.course.id)

    def set_current(self, current: bool) -> None:
        self.configure(
            fg_color=THEME.selected_row if current else THEME.surface,
            border_width=1 if current else 0,
            border_color=THEME.primary if current else THEME.surface,
        )

    def set_status(self, text: str, color: str = THEME.primary) -> None:
        self.status_label.configure(text=text, text_color=color)


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(f"BK-LMS Downloader v{__version__}")
        self.geometry("1180x790")
        self.minsize(1000, 700)
        self.configure(fg_color=THEME.bg)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.driver = None
        self.events: queue.Queue[dict] = queue.Queue()
        self.store = CourseStore()
        self.settings = AppSettings()
        self.syncing = False
        self.update_info: UpdateInfo | None = None
        self.current_course_id: str | None = None
        self.course_rows: dict[str, CourseRow] = {}
        self.progress_total = 1
        self.icons = self._create_icons()

        self.login_status_var = tk.StringVar(value="Chưa đăng nhập")
        self.course_detail_var = tk.StringVar(value="Chọn course để xem thư mục lưu.")
        self.overall_var = tk.StringVar(value="Chưa có phiên đồng bộ")
        self.current_course_var = tk.StringVar(value="Sẵn sàng đồng bộ")
        self.summary_var = tk.StringVar(value="Chưa có kết quả đồng bộ.")

        self._build_ui()
        self._refresh_courses()
        self._set_login_status("Chưa đăng nhập", "idle")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_events)
        self._check_for_updates()

    def _create_icons(self) -> dict[str, ctk.CTkImage]:
        return {
            "brand": icon("brand", THEME.primary, 22),
            "chrome": icon("chrome", THEME.primary, 24),
            "check": icon("check", THEME.success, 19),
            "info": icon("info", THEME.primary, 19),
            "cap": icon("cap", THEME.primary, 23),
            "plus": icon("plus", THEME.primary, 17),
            "download": icon("download", THEME.primary, 17),
            "edit": icon("edit", THEME.primary, 17),
            "trash": icon("trash", THEME.danger, 17),
            "folder": icon("folder", THEME.text, 18),
            "tools": icon("tools", THEME.text, 17),
            "sync": icon("sync", THEME.primary, 19),
            "sync_white": icon("sync", "#FFFFFF", 19),
            "chevron": icon("chevron", THEME.text, 15),
        }

    def _build_ui(self) -> None:
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color=THEME.bg, corner_radius=0)
        self.main_scroll.grid(row=0, column=0, sticky="nsew")
        self.main_scroll.grid_columnconfigure(0, weight=1)

        self._build_top_area()
        self._build_courses_card()
        self._build_sync_card()
        ctk.CTkLabel(
            self.main_scroll,
            text="Video luôn được bỏ qua. Tài liệu được gom gọn theo nhóm để dễ tìm.",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).grid(row=3, column=0, sticky="w", padx=24, pady=(0, 16))

    def _build_top_area(self) -> None:
        top = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 14))
        top.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(top, text="", image=self.icons["brand"], width=26).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top,
            text="BK-LMS Downloader",
            font=(THEME.font_family, 19, "bold"),
            text_color=THEME.text,
        ).grid(row=0, column=1, sticky="w", padx=(6, 28))
        self.login_btn = ctk.CTkButton(
            top,
            text="Mở Chrome để đăng nhập",
            image=self.icons["chrome"],
            compound="left",
            command=self._open_login,
            height=44,
            font=(THEME.font_family, 14, "bold"),
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=11,
        )
        self.login_btn.grid(row=0, column=2, sticky="w", padx=(0, 14))

        self.login_badge = ctk.CTkFrame(
            top,
            fg_color=THEME.primary_soft,
            border_color="#C9DDF9",
            border_width=1,
            corner_radius=11,
            height=40,
        )
        self.login_badge.grid(row=0, column=3, sticky="w")
        self.login_badge_icon = ctk.CTkLabel(self.login_badge, text="", image=self.icons["info"], width=24)
        self.login_badge_icon.pack(side="left", padx=(12, 5), pady=8)
        self.login_badge_label = ctk.CTkLabel(
            self.login_badge,
            textvariable=self.login_status_var,
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.primary,
        )
        self.login_badge_label.pack(side="left", padx=(0, 12), pady=8)

        privacy = ctk.CTkFrame(top, fg_color="transparent")
        privacy.grid(row=0, column=4, sticky="e", padx=(16, 0))
        ctk.CTkLabel(privacy, text="", image=self.icons["info"], width=22).pack(side="left")
        ctk.CTkLabel(
            privacy,
            text="Ứng dụng không lưu mật khẩu/cookie.",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).pack(side="left", padx=(4, 0))

        self.update_notice = ctk.CTkFrame(top, fg_color=THEME.primary_soft, corner_radius=9)
        self.update_notice_var = tk.StringVar()
        ctk.CTkLabel(
            self.update_notice,
            textvariable=self.update_notice_var,
            font=(THEME.font_family, 12, "bold"),
            text_color=THEME.primary,
        ).pack(side="left", padx=(10, 3), pady=6)
        ctk.CTkButton(
            self.update_notice,
            text="Xem cập nhật",
            command=self._open_update,
            height=27,
            width=100,
            fg_color="transparent",
            hover_color="#DDEEFF",
            text_color=THEME.primary,
            corner_radius=7,
        ).pack(side="left", padx=(0, 5), pady=4)

    def _build_courses_card(self) -> None:
        self.courses_card = self._card(self.main_scroll)
        self.courses_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.courses_card.grid_columnconfigure(0, weight=1)
        self.courses_card.grid_rowconfigure(1, weight=1)
        self._card_title(self.courses_card, "cap", "Khóa học của tôi", 0)

        table = ctk.CTkFrame(
            self.courses_card,
            fg_color=THEME.surface,
            border_color=THEME.border,
            border_width=1,
            corner_radius=11,
        )
        table.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        table.grid_columnconfigure(2, weight=1)
        headers = (("Chọn", 0), ("Mã môn", 1), ("Tên môn", 2), ("Lần đồng bộ gần nhất", 3), ("Trạng thái", 4))
        widths = (52, 90, 0, 160, 145)
        for (text, column), width in zip(headers, widths):
            ctk.CTkLabel(
                table,
                text=text,
                width=width if width else 0,
                anchor="w",
                font=(THEME.font_family, 12, "bold"),
                text_color=THEME.muted_text,
            ).grid(row=0, column=column, sticky="ew" if column == 2 else "w", padx=(14 if column == 0 else 8, 8), pady=11)
        ctk.CTkFrame(table, fg_color=THEME.border, height=1, corner_radius=0).grid(
            row=1, column=0, columnspan=5, sticky="ew"
        )
        self.course_scroll = ctk.CTkScrollableFrame(
            table,
            fg_color=THEME.surface,
            corner_radius=0,
            height=218,
            scrollbar_button_color="#C9D3DF",
            scrollbar_button_hover_color="#AAB8C8",
        )
        self.course_scroll.grid(row=2, column=0, columnspan=5, sticky="ew", padx=1, pady=(1, 2))
        self.course_scroll.grid_columnconfigure(0, weight=1)

        self.course_detail_label = ctk.CTkLabel(
            self.courses_card,
            textvariable=self.course_detail_var,
            anchor="w",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        )
        self.course_detail_label.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))

        controls = ctk.CTkFrame(self.courses_card, fg_color="transparent")
        controls.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 9))
        controls.grid_columnconfigure(1, weight=1)
        action_left = ctk.CTkFrame(controls, fg_color="transparent")
        action_left.grid(row=0, column=0, sticky="w")
        self.add_btn = self._outline_button(action_left, "Thêm course", "plus", self._add_course)
        self.import_btn = self._outline_button(action_left, "Nhập từ BK-LMS", "download", self._import_courses)
        self.edit_btn = self._outline_button(action_left, "Sửa", "edit", self._edit_course)
        self.delete_btn = self._outline_button(action_left, "Xóa", "trash", self._delete_course, danger=True)
        self.open_btn = self._outline_button(action_left, "Mở thư mục", "folder", self._open_course_folder)
        for button in (self.add_btn, self.import_btn, self.edit_btn, self.delete_btn, self.open_btn):
            button.pack(side="left", padx=(0, 7))
        self.tools_btn = self._outline_button(controls, "Công cụ", "tools", self._show_tools_menu)
        self.tools_btn.grid(row=0, column=2, sticky="e")

        sync_actions = ctk.CTkFrame(self.courses_card, fg_color="transparent")
        sync_actions.grid(row=4, column=0, sticky="w", padx=14, pady=(0, 14))
        self.sync_selected_btn = ctk.CTkButton(
            sync_actions,
            text="Sync selected",
            image=self.icons["sync"],
            compound="left",
            command=lambda: self._start_sync(True),
            height=42,
            width=190,
            font=(THEME.font_family, 14, "bold"),
            fg_color=THEME.surface,
            hover_color=THEME.primary_soft,
            text_color=THEME.primary,
            border_color=THEME.primary,
            border_width=1,
            corner_radius=THEME.button_radius,
        )
        self.sync_selected_btn.pack(side="left", padx=(0, 10))
        self.sync_all_btn = ctk.CTkButton(
            sync_actions,
            text="Sync all",
            image=self.icons["sync_white"],
            compound="left",
            command=lambda: self._start_sync(False),
            height=42,
            width=170,
            font=(THEME.font_family, 14, "bold"),
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=THEME.button_radius,
        )
        self.sync_all_btn.pack(side="left")

    def _build_sync_card(self) -> None:
        sync_card = self._card(self.main_scroll)
        sync_card.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        sync_card.grid_columnconfigure(0, weight=4)
        sync_card.grid_columnconfigure(1, weight=5)
        self._card_title(sync_card, "sync", "Đồng bộ", 0, columnspan=2)

        progress_area = ctk.CTkFrame(sync_card, fg_color="transparent")
        progress_area.grid(row=1, column=0, sticky="nsew", padx=(18, 14), pady=(0, 18))
        progress_area.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            progress_area,
            textvariable=self.current_course_var,
            anchor="w",
            font=(THEME.font_family, 14, "bold"),
            text_color=THEME.text,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            progress_area,
            textvariable=self.overall_var,
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.muted_text,
        ).grid(row=0, column=1, sticky="e")
        self.progress = ctk.CTkProgressBar(
            progress_area,
            height=11,
            corner_radius=6,
            fg_color="#E2E8F0",
            progress_color=THEME.primary,
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 16))
        self.progress.set(0)
        self.summary_line = ctk.CTkFrame(progress_area, fg_color="transparent")
        self.summary_line.grid(row=2, column=0, columnspan=2, sticky="w")
        self.summary_new = ctk.CTkLabel(
            self.summary_line,
            textvariable=self.summary_var,
            font=(THEME.font_family, 13, "bold"),
            text_color=THEME.muted_text,
        )
        self.summary_new.pack(side="left")
        self.summary_skipped = ctk.CTkLabel(
            self.summary_line,
            text="",
            font=(THEME.font_family, 13),
            text_color=THEME.primary,
        )
        self.summary_skipped.pack(side="left")
        self.summary_errors = ctk.CTkLabel(
            self.summary_line,
            text="",
            font=(THEME.font_family, 13),
            text_color=THEME.danger,
        )
        self.summary_errors.pack(side="left")

        log_area = ctk.CTkFrame(
            sync_card,
            fg_color=THEME.inset,
            border_color=THEME.border,
            border_width=1,
            corner_radius=11,
        )
        log_area.grid(row=1, column=1, sticky="nsew", padx=(0, 18), pady=(0, 18))
        log_area.grid_columnconfigure(0, weight=1)
        log_area.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            log_area,
            text="Hoạt động gần đây",
            font=(THEME.font_family, 12, "bold"),
            text_color=THEME.muted_text,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 5))
        self.log_text = ctk.CTkTextbox(
            log_area,
            height=148,
            fg_color=THEME.surface,
            border_width=0,
            corner_radius=8,
            text_color="#344054",
            font=("Cascadia Mono", 12),
            wrap="word",
            scrollbar_button_color="#C9D3DF",
            scrollbar_button_hover_color="#AAB8C8",
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.log_text.configure(state="disabled")

    def _card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=THEME.surface,
            border_color=THEME.border,
            border_width=1,
            corner_radius=THEME.radius,
        )

    def _card_title(self, parent, icon_name: str, text: str, row: int, columnspan: int = 1) -> None:
        title = ctk.CTkFrame(parent, fg_color="transparent")
        title.grid(row=row, column=0, columnspan=columnspan, sticky="w", padx=18, pady=(16, 12))
        ctk.CTkLabel(title, text="", image=self.icons[icon_name], width=28).pack(side="left")
        ctk.CTkLabel(
            title,
            text=text,
            font=(THEME.font_family, 18, "bold"),
            text_color=THEME.text,
        ).pack(side="left", padx=(5, 0))

    def _outline_button(self, parent, text: str, icon_name: str, command, *, danger: bool = False) -> ctk.CTkButton:
        color = THEME.danger if danger else THEME.primary
        hover = THEME.danger_soft if danger else THEME.primary_soft
        return ctk.CTkButton(
            parent,
            text=text,
            image=self.icons[icon_name],
            compound="left",
            command=command,
            height=38,
            fg_color=THEME.surface,
            hover_color=hover,
            text_color=color,
            border_color=THEME.border,
            border_width=1,
            corner_radius=THEME.button_radius,
            font=(THEME.font_family, 13),
        )

    def _set_login_status(self, text: str, kind: str) -> None:
        palette = {
            "success": (THEME.success_soft, "#BDE7C9", THEME.success, self.icons["check"]),
            "busy": (THEME.primary_soft, "#C9DDF9", THEME.primary, self.icons["sync"]),
            "error": (THEME.danger_soft, "#F4C7CD", THEME.danger, self.icons["info"]),
            "idle": (THEME.primary_soft, "#C9DDF9", THEME.primary, self.icons["info"]),
        }
        fg, border, color, image = palette[kind]
        self.login_status_var.set(text)
        self.login_badge.configure(fg_color=fg, border_color=border)
        self.login_badge_label.configure(text_color=color)
        self.login_badge_icon.configure(image=image)

    def _set_summary_message(self, message: str) -> None:
        self.summary_var.set(message)
        self.summary_new.configure(text_color=THEME.muted_text)
        self.summary_skipped.configure(text="")
        self.summary_errors.configure(text="")

    def _set_summary_counts(self, downloaded: int, skipped: int, errors: int) -> None:
        self.summary_var.set(f"{downloaded} file mới")
        self.summary_new.configure(text_color=THEME.success)
        self.summary_skipped.configure(text=f"  •  {skipped} giữ nguyên")
        self.summary_errors.configure(text=f"  •  {errors} lỗi")

    def _refresh_courses(self) -> None:
        for row in self.course_rows.values():
            row.destroy()
        self.course_rows.clear()
        courses = self.store.list()
        for index, course in enumerate(courses):
            row = CourseRow(self.course_scroll, course, self._select_course, self._toggle_course)
            row.grid(row=index, column=0, sticky="ew", padx=5, pady=2)
            row.set_current(course.id == self.current_course_id)
            self.course_rows[course.id] = row
        if self.current_course_id and self.store.get(self.current_course_id):
            self._show_course_detail(self.current_course_id)
        elif not courses:
            self.current_course_id = None
            self.course_detail_var.set("Chưa có course. Hãy thêm course đầu tiên của bạn.")
        else:
            self.course_detail_var.set("Chọn course để xem thư mục lưu.")

    @staticmethod
    def _format_last_sync(value: str | None) -> str:
        if not value:
            return "Chưa đồng bộ"
        try:
            return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
        except ValueError:
            return value

    @staticmethod
    def _status_text(course: Course) -> tuple[str, str]:
        if course.last_status == "never":
            return "Chưa đồng bộ", THEME.muted_text
        if course.last_status == "success":
            return (f"{course.last_downloaded} file mới" if course.last_downloaded else "Hoàn tất"), THEME.success
        if course.last_status == "up_to_date":
            return "Giữ nguyên", THEME.primary
        return f"{max(1, course.last_errors)} lỗi", THEME.danger

    def _select_course(self, course_id: str) -> None:
        self.current_course_id = course_id
        for row_id, row in self.course_rows.items():
            row.set_current(row_id == course_id)
        self._show_course_detail(course_id)

    def _toggle_course(self, course_id: str, selected: bool) -> None:
        if self.syncing:
            return
        self.store.edit(course_id, selected=selected)
        self._refresh_courses()
        self._select_course(course_id)

    def _show_course_detail(self, course_id: str) -> None:
        course = self.store.get(course_id)
        if course is not None:
            self.course_detail_var.set(f"Thư mục lưu: {course.output}")

    def _selected_course(self) -> Course | None:
        course = self.store.get(self.current_course_id or "")
        if course is None:
            messagebox.showwarning("Chọn course", "Hãy chọn một course trong danh sách.", parent=self)
        return course

    def _add_course(self) -> None:
        if self.syncing:
            return

        def save(url: str, name: str, output: str) -> None:
            self.settings.set_last_output_dir(output)
            course = self.store.add(url, output, name=name)
            self.current_course_id = course.id
            self._refresh_courses()

        CourseDialog(self, None, save)

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

    def course_exists(self, url: str) -> bool:
        return any(course.url == url for course in self.store.list())

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
            self.current_course_id = None
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
            messagebox.showerror("Mở thư mục", "Không thể mở thư mục đã chọn.", parent=self)

    def _show_tools_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False, font=(THEME.font_family, 10))
        menu.add_command(label="Chuẩn bị cho AI", command=self._prepare_for_ai)
        try:
            menu.tk_popup(self.tools_btn.winfo_rootx(), self.tools_btn.winfo_rooty() + self.tools_btn.winfo_height())
        finally:
            menu.grab_release()

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
        self._set_summary_message("Đang xử lý tài liệu đã tải...")

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
        self._set_summary_message("Bạn vẫn có thể thêm course bằng URL nếu cần.")

        def worker() -> None:
            try:
                wait_page(self.driver, extra=0.1)
                session = make_session(self.driver)
                courses = discover_courses_with_browser_fallback(session, self.driver)
                self.events.put({"event": "courses_discovered", "courses": courses})
            except (CourseDiscoveryError, SessionExpiredError) as exc:
                self.events.put({"event": "course_discovery_error", "error": str(exc)})
            except Exception:
                LOG.exception("Course discovery browser fallback failed")
                self.events.put(
                    {
                        "event": "course_discovery_error",
                        "error": "Không tìm thấy course nào. Bạn vẫn có thể thêm course bằng URL.",
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_imported_courses(self, courses: list[DiscoveredCourse]) -> None:
        self._set_busy(False)
        self.current_course_var.set("Sẵn sàng đồng bộ")
        self._set_login_status("Đã đăng nhập BK-LMS", "success")
        if not courses:
            self._set_summary_message("Không tìm thấy course nào để nhập.")
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
            self._set_summary_message(f"Đã thêm {len(selected)} course. Sẵn sàng đồng bộ.")

        ImportCoursesDialog(self, courses, add_selected)

    def _open_login(self) -> None:
        if self.syncing:
            return
        self.login_btn.configure(state="disabled")
        self._set_login_status("Đang mở Chrome...", "busy")

        def worker() -> None:
            try:
                if self.driver is None:
                    self.driver = create_driver()
                self.driver.get(LMS_BASE)
                wait_page(self.driver)
                self.events.put({"event": "login_ready"})
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
        self._set_login_status("Đã đăng nhập BK-LMS", "success")
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
        self.progress_total = len(courses)
        self.progress.set(0)
        self.overall_var.set(f"0 / {len(courses)} course")
        self.current_course_var.set("Đang kiểm tra phiên đăng nhập...")
        self._set_summary_message("Đang đồng bộ...")
        self._set_login_status("Đang đồng bộ...", "busy")
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
            self._set_login_status("Chrome đã mở — hãy đăng nhập", "success")
            self.login_btn.configure(state="normal")
        elif kind == "login_error":
            self._set_login_status("Không mở được Chrome", "error")
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
            self._set_summary_message(message)
            if "đăng nhập" in message.lower():
                self._set_login_status("Phiên đăng nhập hết hạn", "error")
            messagebox.showwarning("Nhập từ BK-LMS", message, parent=self)
        elif kind == "ai_prepare_complete":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self._set_summary_message("Đã chuẩn bị course cho AI.")
            messagebox.showinfo("Chuẩn bị cho AI", f"Đã tạo knowledge base tại:\n{event['output']}", parent=self)
        elif kind == "ai_prepare_missing":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self._set_summary_message("Tính năng AI cần cài thêm gói tuỳ chọn.")
            messagebox.showinfo("Chuẩn bị cho AI", event["error"], parent=self)
        elif kind == "ai_prepare_error":
            self._set_busy(False)
            self.current_course_var.set("Sẵn sàng đồng bộ")
            self._set_summary_message("Không thể chuẩn bị course cho AI.")
            messagebox.showwarning("Chuẩn bị cho AI", event["error"], parent=self)
        elif kind == "update_available":
            self.update_info = event["update"]
            self.update_notice_var.set(f"Có bản cập nhật v{self.update_info.latest_version}")
            self.update_notice.grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
        elif kind == "course_sync_start":
            course: Course = event["course"]
            index, total = event["index"], event["total"]
            self.overall_var.set(f"{index} / {total} course")
            self.current_course_var.set(f"Đang đồng bộ: {course.code or '-'} — {course.display_name}")
            row = self.course_rows.get(course.id)
            if row is not None:
                row.set_status("Đang đồng bộ...", THEME.primary)
            self._log(f"[SYNC] {course.code or '-'} - {course.display_name}")
        elif kind == "crawler_event":
            self._handle_crawler_event(event["activity"])
        elif kind == "course_sync_complete":
            result = event["result"]
            self.progress.set(min(1, event["index"] / max(1, event["total"])))
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
            self._set_login_status("Có lỗi", "error")
            self._set_summary_message("Không thể hoàn tất đồng bộ.")
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
        self.progress.set(1 if total else 0)
        self.overall_var.set(f"{len(batch.results)} / {total} course")
        self._set_summary_counts(batch.downloaded, batch.skipped, batch.errors)
        self._refresh_courses()

        if batch.authentication_error:
            self._set_login_status("Phiên đăng nhập hết hạn", "error")
            messagebox.showwarning(
                "Phiên đăng nhập hết hạn",
                f"{batch.downloaded} file mới • {batch.skipped} giữ nguyên • {batch.errors} lỗi\n\n"
                "Hãy đăng nhập lại trong Chrome rồi thử lại.",
                parent=self,
            )
        else:
            self._set_login_status("Đã đăng nhập BK-LMS", "success")
            messagebox.showinfo(
                "Đồng bộ hoàn tất",
                f"{batch.downloaded} file mới • {batch.skipped} giữ nguyên • {batch.errors} lỗi",
                parent=self,
            )

    def _log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text.rstrip()}\n")
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
