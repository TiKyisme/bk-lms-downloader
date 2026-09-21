"""Private-by-default in-app feedback drafting and GitHub issue handoff."""

from __future__ import annotations

import platform as platform_module
import tkinter as tk
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

import customtkinter as ctk
from tkinter import messagebox

from .ui_theme import THEME


GITHUB_ISSUES_NEW_URL = "https://github.com/TiKyisme/bk-lms-downloader/issues/new"
FEEDBACK_TEMPLATE = "feedback.md"
FEEDBACK_TYPES = ("Báo lỗi", "Đề xuất tính năng", "Khác")


def current_platform_label() -> str:
    return f"{platform_module.system()} {platform_module.release()}".strip()


@dataclass(frozen=True)
class FeedbackDraft:
    feedback_type: str
    title: str
    description: str
    app_version: str
    platform: str

    def validate(self) -> str | None:
        if self.feedback_type not in FEEDBACK_TYPES:
            return "Hãy chọn loại phản hồi hợp lệ."
        if len(self.title.strip()) < 3:
            return "Tiêu đề cần có ít nhất 3 ký tự."
        if len(self.description.strip()) < 10:
            return "Mô tả cần có ít nhất 10 ký tự."
        return None

    def issue_body(self) -> str:
        return "\n".join(
            (
                "## Loại phản hồi",
                self.feedback_type,
                "",
                "## Mô tả",
                self.description.strip(),
                "",
                "## Thông tin ứng dụng",
                f"- Phiên bản: {self.app_version}",
                f"- Hệ điều hành: {self.platform}",
                "",
                "_Vui lòng không thêm MSSV, mật khẩu, cookie, tài liệu môn học hoặc thông tin cá nhân._",
            )
        )

    def github_issue_url(self) -> str:
        return GITHUB_ISSUES_NEW_URL + "?" + urlencode(
            {
                "template": FEEDBACK_TEMPLATE,
                "title": self.title.strip(),
                "body": self.issue_body(),
            },
            encoding="utf-8",
        )


class FeedbackDialog(ctk.CTkToplevel):
    """Draft locally, then let the user explicitly review on GitHub."""

    def __init__(
        self,
        parent: ctk.CTk,
        *,
        app_version: str,
        platform: str,
        open_url: Callable[[str], bool],
    ):
        super().__init__(parent)
        self.app_version = app_version
        self.platform = platform
        self.open_url = open_url
        self.prepared_url = ""
        self.title("Gửi phản hồi")
        self.geometry("620x610")
        self.minsize(540, 540)
        self.configure(fg_color=THEME.bg)
        self.transient(parent)
        self.grab_set()

        self.feedback_type_var = tk.StringVar(value=FEEDBACK_TYPES[0])
        self.title_var = tk.StringVar()
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
        card.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            card,
            text="Gửi phản hồi",
            font=(THEME.font_family, 18, "bold"),
            text_color=THEME.text,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        ctk.CTkLabel(
            card,
            text="Bạn sẽ xem và tự gửi phản hồi trên GitHub; ứng dụng không gửi dữ liệu tự động.",
            wraplength=540,
            justify="left",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))

        fields = ctk.CTkFrame(card, fg_color="transparent")
        fields.grid(row=2, column=0, sticky="ew", padx=18)
        fields.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(fields, text="Loại phản hồi", font=(THEME.font_family, 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 9)
        )
        ctk.CTkOptionMenu(
            fields,
            variable=self.feedback_type_var,
            values=list(FEEDBACK_TYPES),
            height=34,
            fg_color=THEME.primary,
            button_color=THEME.primary_hover,
            button_hover_color=THEME.primary_hover,
        ).grid(row=0, column=1, sticky="e", pady=(0, 9))
        ctk.CTkLabel(fields, text="Tiêu đề", font=(THEME.font_family, 12, "bold")).grid(
            row=1, column=0, sticky="w", pady=(0, 9)
        )
        ctk.CTkEntry(
            fields,
            textvariable=self.title_var,
            height=36,
            border_color=THEME.border,
            corner_radius=9,
        ).grid(row=1, column=1, sticky="ew", pady=(0, 9))

        ctk.CTkLabel(
            card,
            text="Mô tả",
            font=(THEME.font_family, 12, "bold"),
        ).grid(row=3, column=0, sticky="w", padx=18, pady=(12, 6))
        self.description_box = ctk.CTkTextbox(
            card,
            height=180,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
            font=(THEME.font_family, 13),
        )
        self.description_box.grid(row=4, column=0, sticky="nsew", padx=18)

        details = ctk.CTkFrame(card, fg_color=THEME.inset, corner_radius=9)
        details.grid(row=5, column=0, sticky="ew", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            details,
            text=f"Phiên bản: {self.app_version}    •    Hệ điều hành: {self.platform}",
            font=(THEME.font_family, 12),
            text_color=THEME.muted_text,
        ).pack(anchor="w", padx=12, pady=(8, 3))
        ctk.CTkLabel(
            details,
            text="Không gửi MSSV, mật khẩu, cookie, tài liệu môn học hoặc thông tin cá nhân.",
            wraplength=520,
            justify="left",
            font=(THEME.font_family, 12, "bold"),
            text_color=THEME.danger,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.fallback_var = tk.StringVar()
        self.fallback_entry = ctk.CTkEntry(
            card,
            textvariable=self.fallback_var,
            state="disabled",
            height=34,
            border_color=THEME.border,
        )
        self.copy_btn = ctk.CTkButton(
            card,
            text="Sao chép liên kết",
            command=self._copy_url,
            height=32,
            width=130,
            fg_color=THEME.primary_soft,
            hover_color="#DDEEFF",
            text_color=THEME.primary,
            corner_radius=9,
        )

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=7, column=0, sticky="e", padx=18, pady=(12, 18))
        ctk.CTkButton(
            actions,
            text="Đóng",
            command=self.destroy,
            height=36,
            width=88,
            fg_color=THEME.surface,
            hover_color=THEME.inset,
            text_color=THEME.text,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
        ).pack(side="right")
        ctk.CTkButton(
            actions,
            text="Mở GitHub để gửi",
            command=self._open_github,
            height=36,
            width=152,
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=9,
        ).pack(side="right", padx=(0, 8))

    def _draft(self) -> FeedbackDraft:
        return FeedbackDraft(
            feedback_type=self.feedback_type_var.get(),
            title=self.title_var.get(),
            description=self.description_box.get("1.0", "end-1c"),
            app_version=self.app_version,
            platform=self.platform,
        )

    def _open_github(self) -> None:
        draft = self._draft()
        error = draft.validate()
        if error:
            messagebox.showwarning("Phản hồi", error, parent=self)
            return
        self.prepared_url = draft.github_issue_url()
        if self.open_url(self.prepared_url):
            messagebox.showinfo(
                "Phản hồi",
                "GitHub đã được mở. Hãy kiểm tra nội dung rồi tự quyết định có gửi hay không.",
                parent=self,
            )
            return
        self.fallback_var.set(self.prepared_url)
        self.fallback_entry.grid(row=6, column=0, sticky="ew", padx=(18, 156), pady=(2, 0))
        self.copy_btn.grid(row=6, column=0, sticky="e", padx=18, pady=(2, 0))
        messagebox.showwarning(
            "Không thể mở trình duyệt",
            "Hãy sao chép liên kết bên dưới và mở thủ công trong trình duyệt.",
            parent=self,
        )

    def _copy_url(self) -> None:
        if not self.prepared_url:
            return
        self.clipboard_clear()
        self.clipboard_append(self.prepared_url)
        self.update()
        messagebox.showinfo("Phản hồi", "Đã sao chép liên kết GitHub.", parent=self)
