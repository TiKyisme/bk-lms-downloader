"""First-run tutorial state and a stable anchored CustomTkinter guide."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import customtkinter as ctk

from .app_settings import ONBOARDING_VERSION
from .ui_theme import THEME

PANEL_WIDTH = 590
PANEL_HEIGHT = 370
PANEL_MARGIN = 16


def panel_position(
    *,
    parent_x: int,
    parent_y: int,
    parent_width: int,
    parent_height: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """Center a fixed tutorial panel over its parent while keeping it visible."""
    x = parent_x + (parent_width - PANEL_WIDTH) // 2
    y = parent_y + (parent_height - PANEL_HEIGHT) // 2
    max_x = max(PANEL_MARGIN, screen_width - PANEL_WIDTH - PANEL_MARGIN)
    max_y = max(PANEL_MARGIN, screen_height - PANEL_HEIGHT - PANEL_MARGIN)
    return max(PANEL_MARGIN, min(x, max_x)), max(PANEL_MARGIN, min(y, max_y))


def geometry_units_for_scaling(window_scaling: float) -> tuple[int, int]:
    """Convert fixed physical panel dimensions to CustomTkinter geometry units."""
    scale = window_scaling if window_scaling > 0 else 1.0
    return max(1, round(PANEL_WIDTH / scale)), max(1, round(PANEL_HEIGHT / scale))


@dataclass(frozen=True)
class OnboardingStep:
    title: str
    body: str
    target_key: str | None = None


ONBOARDING_STEPS = (
    OnboardingStep(
        "Chào mừng đến với BK-LMS Downloader",
        "Ứng dụng giúp bạn nhập môn học, đồng bộ tài liệu BK-LMS và giữ thư mục học tập gọn gàng trên máy.",
    ),
    OnboardingStep(
        "Đăng nhập qua Chrome",
        "Bấm “Mở Chrome để đăng nhập”, rồi đăng nhập trực tiếp trên trang BK-LMS. Ứng dụng không hỏi hoặc lưu mật khẩu.",
        "login",
    ),
    OnboardingStep(
        "Nhập môn học",
        "Bấm “Nhập từ BK-LMS” để chọn các môn đã đăng ký và thư mục lưu. Bạn vẫn có thể dùng “Thêm course” để nhập thủ công.",
        "import",
    ),
    OnboardingStep(
        "Chọn môn bằng checkbox",
        "Đánh dấu checkbox của những môn bạn muốn thao tác. Lựa chọn này quyết định các hành động dành cho môn đã chọn.",
        "courses",
    ),
    OnboardingStep(
        "Đồng bộ tài liệu",
        "“Đồng bộ đã chọn” tải các môn đã đánh dấu; “Đồng bộ tất cả” xử lý toàn bộ danh sách. Các file không đổi sẽ được giữ lại và hủy đồng bộ vẫn giữ file đã hoàn tất.",
        "sync",
    ),
    OnboardingStep(
        "Chuẩn bị môn học cho AI",
        "Trong “Công cụ”, bạn có thể tạo một AI Study Pack ZIP riêng cho từng môn đã đồng bộ. ZIP được tạo hoàn toàn trên máy; bạn tự chọn có tải nó lên ChatGPT hay không.",
        "tools",
    ),
)


@dataclass
class OnboardingState:
    """Pure tutorial navigation state, independently testable without Tk."""

    step_index: int = 0
    manual_replay: bool = False

    @property
    def total_steps(self) -> int:
        return len(ONBOARDING_STEPS)

    @property
    def step(self) -> OnboardingStep:
        return ONBOARDING_STEPS[self.step_index]

    @property
    def is_first(self) -> bool:
        return self.step_index == 0

    @property
    def is_last(self) -> bool:
        return self.step_index == self.total_steps - 1

    def next(self) -> None:
        if not self.is_last:
            self.step_index += 1

    def previous(self) -> None:
        if not self.is_first:
            self.step_index -= 1


class OnboardingDialog(ctk.CTkToplevel):
    """A cross-platform anchored tutorial card without fragile window overlays."""

    def __init__(
        self,
        parent: ctk.CTk,
        *,
        target_for_step: Callable[[str | None], object | None],
        reveal_target: Callable[[str | None], None],
        on_done: Callable[[], None],
        manual_replay: bool = False,
    ):
        super().__init__(parent)
        self.parent = parent
        self.target_for_step = target_for_step
        self.reveal_target = reveal_target
        self.on_done = on_done
        self.tutorial_state = OnboardingState(manual_replay=manual_replay)
        self._highlighted: object | None = None
        self._highlight_style: tuple[object, object] | None = None

        self.title("Hướng dẫn nhanh")
        geometry_width, geometry_height = self._geometry_units()
        self.geometry(f"{geometry_width}x{geometry_height}")
        self.minsize(geometry_width, geometry_height)
        self.maxsize(geometry_width, geometry_height)
        self.resizable(False, False)
        self.configure(fg_color=THEME.bg)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._finish)
        self._build()
        self.after(40, self._open)

    def _open(self) -> None:
        self.parent.update_idletasks()
        self.update_idletasks()
        x, y = panel_position(
            parent_x=self.parent.winfo_rootx(),
            parent_y=self.parent.winfo_rooty(),
            parent_width=self.parent.winfo_width(),
            parent_height=self.parent.winfo_height(),
            screen_width=self.winfo_screenwidth(),
            screen_height=self.winfo_screenheight(),
        )
        geometry_width, geometry_height = self._geometry_units()
        self.geometry(f"{geometry_width}x{geometry_height}+{x}+{y}")
        self.lift()
        self._render_step()

    def _geometry_units(self) -> tuple[int, int]:
        try:
            scaling = float(self._get_window_scaling())
        except Exception:
            scaling = 1.0
        return geometry_units_for_scaling(scaling)

    def _build(self) -> None:
        card = ctk.CTkFrame(
            self,
            fg_color=THEME.surface,
            border_color=THEME.border,
            border_width=1,
            corner_radius=THEME.radius,
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        self.progress_label = ctk.CTkLabel(
            card,
            font=(THEME.font_family, 12, "bold"),
            text_color=THEME.primary,
        )
        self.progress_label.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 5))
        self.title_label = ctk.CTkLabel(
            card,
            anchor="w",
            justify="left",
            wraplength=PANEL_WIDTH - 72,
            font=(THEME.font_family, 17, "bold"),
            text_color=THEME.text,
        )
        self.title_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        self.body_label = ctk.CTkLabel(
            card,
            anchor="nw",
            justify="left",
            wraplength=PANEL_WIDTH - 72,
            font=(THEME.font_family, 13),
            text_color=THEME.muted_text,
        )
        self.body_label.grid(row=2, column=0, sticky="new", padx=18)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=18, pady=(18, 18))
        actions.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            actions,
            text="Bỏ qua",
            command=self._finish,
            height=34,
            width=82,
            fg_color="transparent",
            hover_color=THEME.inset,
            text_color=THEME.muted_text,
            corner_radius=9,
        ).grid(row=0, column=0, sticky="w")
        self.back_btn = ctk.CTkButton(
            actions,
            text="Quay lại",
            command=self._previous,
            height=34,
            width=88,
            fg_color=THEME.surface,
            hover_color=THEME.inset,
            text_color=THEME.text,
            border_color=THEME.border,
            border_width=1,
            corner_radius=9,
        )
        self.back_btn.grid(row=0, column=2, padx=(0, 8))
        self.next_btn = ctk.CTkButton(
            actions,
            command=self._next,
            height=34,
            width=82,
            fg_color=THEME.primary,
            hover_color=THEME.primary_hover,
            corner_radius=9,
        )
        self.next_btn.grid(row=0, column=3)

    def _render_step(self) -> None:
        step = self.tutorial_state.step
        self.progress_label.configure(text=f"{self.tutorial_state.step_index + 1} / {self.tutorial_state.total_steps}")
        self.title_label.configure(text=step.title)
        self.body_label.configure(text=step.body)
        self.back_btn.configure(state="disabled" if self.tutorial_state.is_first else "normal")
        self.next_btn.configure(text="Hoàn tất" if self.tutorial_state.is_last else "Tiếp")
        self._highlight(step.target_key)

    def _highlight(self, target_key: str | None) -> None:
        self._clear_highlight()
        try:
            self.reveal_target(target_key)
        except Exception:
            pass
        target = self.target_for_step(target_key)
        if target is None:
            return
        try:
            original = (target.cget("border_color"), target.cget("border_width"))
            target.configure(border_color=THEME.primary, border_width=2)
        except Exception:
            return
        self._highlighted = target
        self._highlight_style = original

    def _clear_highlight(self) -> None:
        if self._highlighted is not None and self._highlight_style is not None:
            try:
                self._highlighted.configure(
                    border_color=self._highlight_style[0],
                    border_width=self._highlight_style[1],
                )
            except Exception:
                pass
        self._highlighted = None
        self._highlight_style = None

    def _next(self) -> None:
        if self.tutorial_state.is_last:
            self._finish()
            return
        self.tutorial_state.next()
        self._render_step()

    def _previous(self) -> None:
        self.tutorial_state.previous()
        self._render_step()

    def _finish(self) -> None:
        self._clear_highlight()
        try:
            self.on_done()
        finally:
            self.destroy()
