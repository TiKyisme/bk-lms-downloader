from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .auth import create_driver, make_session, wait_page
from .config import DEFAULT_OUTPUT, LMS_BASE
from .crawler import DeepDownloader
from .utils import is_course_url


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"BK-LMS Downloader v{__version__}")
        self.geometry("820x650")
        self.minsize(760, 590)

        self.driver = None
        self.last_output: Path | None = None
        self.events: queue.Queue[dict] = queue.Queue()

        self.course_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.archive_var = tk.BooleanVar(value=False)
        self.linked_var = tk.BooleanVar(value=True)
        self.depth_var = tk.IntVar(value=4)
        self.status_var = tk.StringVar(value="Chưa đăng nhập")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_events)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(7, weight=1)

        title = ttk.Label(outer, text="BK-LMS Downloader", font=("Segoe UI", 20, "bold"))
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="Tải tài liệu học theo đúng section trên BK-LMS. Video luôn được bỏ qua.",
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        login_frame = ttk.Frame(outer)
        login_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.login_btn = ttk.Button(login_frame, text="1. Mở Chrome để đăng nhập", command=self._open_login)
        self.login_btn.pack(side="left")
        ttk.Button(login_frame, text="Dùng course đang mở", command=self._use_current_course).pack(side="left", padx=8)
        ttk.Label(login_frame, textvariable=self.status_var).pack(side="left", padx=8)

        course = ttk.LabelFrame(outer, text="Course", padding=10)
        course.grid(row=3, column=0, sticky="ew", pady=5)
        course.columnconfigure(0, weight=1)
        ttk.Entry(course, textvariable=self.course_var).grid(row=0, column=0, sticky="ew")
        ttk.Label(course, text="Ví dụ: https://lms.hcmut.edu.vn/course/view.php?id=123456").grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )

        dest = ttk.LabelFrame(outer, text="Thư mục lưu", padding=10)
        dest.grid(row=4, column=0, sticky="ew", pady=5)
        dest.columnconfigure(0, weight=1)
        ttk.Entry(dest, textvariable=self.output_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(dest, text="Chọn folder...", command=self._choose_output).grid(row=0, column=1, padx=(8, 0))

        options = ttk.LabelFrame(outer, text="Tuỳ chọn", padding=10)
        options.grid(row=5, column=0, sticky="ew", pady=5)
        ttk.Checkbutton(options, text="Complete archive (HTML + link ngoài)", variable=self.archive_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Đi theo course học liệu liên kết", variable=self.linked_var).grid(row=1, column=0, sticky="w")
        ttk.Label(options, text="Video: luôn bỏ qua để tiết kiệm dung lượng").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(options, text="Độ sâu crawl:").grid(row=0, column=1, padx=(30, 6), sticky="e")
        ttk.Spinbox(options, from_=0, to=8, width=5, textvariable=self.depth_var).grid(row=0, column=2, sticky="w")

        actions = ttk.Frame(outer)
        actions.grid(row=6, column=0, sticky="ew", pady=12)
        self.download_btn = ttk.Button(actions, text="2. TẢI / SYNC TÀI LIỆU", command=self._start_download)
        self.download_btn.pack(side="left")
        self.open_btn = ttk.Button(actions, text="Mở thư mục kết quả", command=self._open_output, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=220)
        self.progress.pack(side="right", fill="x", expand=True, padx=(20, 0))

        log_frame = ttk.LabelFrame(outer, text="Tiến trình", padding=8)
        log_frame.grid(row=7, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        ttk.Label(
            outer,
            text="Đăng nhập diễn ra trên website BK-LMS trong Chrome; ứng dụng không hỏi hoặc lưu mật khẩu.",
        ).grid(row=8, column=0, sticky="w", pady=(10, 0))

    def _log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _emit_from_worker(self, event: dict):
        self.events.put(event)

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("event")
                message = event.get("message", "")
                if message:
                    self._log(message)
                if kind == "login_ready":
                    self.status_var.set("Chrome đã mở — hãy đăng nhập")
                    self.login_btn.configure(state="normal")
                elif kind == "login_error":
                    self.status_var.set("Không mở được Chrome")
                    self.login_btn.configure(state="normal")
                    messagebox.showerror("Không mở được Chrome", event.get("error", message))
                elif kind == "course_complete":
                    output = event.get("output")
                    if output:
                        self.last_output = Path(output)
                        self.open_btn.configure(state="normal")
                elif kind == "job_done":
                    self.progress.stop()
                    self.download_btn.configure(state="normal")
                    self.status_var.set("Hoàn tất")
                    messagebox.showinfo("BK-LMS Downloader", "Đã hoàn tất tải/sync tài liệu.")
                elif kind == "job_error":
                    self.progress.stop()
                    self.download_btn.configure(state="normal")
                    self.status_var.set("Có lỗi")
                    messagebox.showerror("Lỗi", event.get("error", message))
        except queue.Empty:
            pass
        self.after(120, self._drain_events)

    def _open_login(self):
        if self.driver is not None:
            try:
                self.driver.get(LMS_BASE)
                self.driver.switch_to.window(self.driver.current_window_handle)
                self.status_var.set("Chrome đã mở — hãy đăng nhập")
                return
            except Exception:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

        self.login_btn.configure(state="disabled")
        self.status_var.set("Đang mở Chrome...")

        def worker():
            try:
                self.driver = create_driver()
                self.driver.get(LMS_BASE)
                wait_page(self.driver)
                self.events.put({"event": "login_ready", "message": "Chrome đã mở. Hãy đăng nhập BK-LMS trong Chrome."})
            except Exception as exc:
                self.driver = None
                self.events.put({"event": "login_error", "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _use_current_course(self):
        if self.driver is None:
            messagebox.showwarning("Chưa mở Chrome", "Hãy bấm 'Mở Chrome để đăng nhập' trước.")
            return
        try:
            url = self.driver.current_url
            if not is_course_url(url):
                messagebox.showwarning("Chưa ở trang course", "Hãy mở một course BK-LMS trong Chrome rồi thử lại.")
                return
            self.course_var.set(url)
            self.status_var.set("Đã chọn course")
        except Exception as exc:
            messagebox.showerror("Chrome", str(exc))

    def _choose_output(self):
        path = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()))
        if path:
            self.output_var.set(path)

    def _start_download(self):
        if self.driver is None:
            messagebox.showwarning("Chưa đăng nhập", "Hãy mở Chrome và đăng nhập BK-LMS trước.")
            return

        course_url = self.course_var.get().strip()
        if not is_course_url(course_url):
            messagebox.showwarning("Course URL", "URL course BK-LMS không hợp lệ.")
            return

        output = Path(self.output_var.get()).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Thư mục lưu", str(exc))
            return

        max_depth = max(0, int(self.depth_var.get()))
        follow_linked = bool(self.linked_var.get())
        archive_mode = bool(self.archive_var.get())

        self.download_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Đang tải...")
        self._log("=" * 64)
        self._log(f"Course: {course_url}")
        self._log(f"Output: {output}")
        self._log("Video: SKIP (không hỗ trợ tải video)")

        def worker():
            try:
                wait_page(self.driver, extra=0.1)
                session = make_session(self.driver)
                downloader = DeepDownloader(
                    session=session,
                    output=output,
                    force=False,
                    max_depth=max_depth,
                    follow_linked_courses=follow_linked,
                    archive_mode=archive_mode,
                    event_callback=self._emit_from_worker,
                )
                result = downloader.crawl_course(course_url, output, depth=0)
                if result:
                    self.last_output = result
                self.events.put({"event": "job_done"})
            except Exception as exc:
                self.events.put({"event": "job_error", "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _open_output(self):
        path = self.last_output or Path(self.output_var.get())
        if not path.exists():
            messagebox.showwarning("Thư mục", "Chưa tìm thấy thư mục kết quả.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif os.name == "posix":
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Mở thư mục", str(exc))

    def _on_close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
