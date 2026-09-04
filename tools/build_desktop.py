#!/usr/bin/env python3
"""Canonical PyInstaller entrypoint shared by Windows and macOS builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_ICON = REPO_ROOT / "BK-LMS-Downloader-icon-blue.ico"
MACOS_ICON = REPO_ROOT / "build" / "BK-LMS-Downloader.icns"
AI_TOOL = REPO_ROOT / "tools" / "prepare_ai_course.py"


def pyinstaller_arguments(platform_name: str = sys.platform) -> list[str]:
    if platform_name.startswith("win"):
        app_name = "BK-LMS-Downloader"
        icon_path = WINDOWS_ICON
        data_separator = ";"
        platform_arguments = ["--onefile"]
    elif platform_name == "darwin":
        app_name = "BK-LMS Downloader"
        icon_path = MACOS_ICON
        data_separator = ":"
        platform_arguments = []
    else:
        raise RuntimeError(f"Unsupported desktop packaging platform: {platform_name}")

    return [
        "--noconfirm",
        "--clean",
        "--windowed",
        *platform_arguments,
        "--name",
        app_name,
        "--paths",
        str(REPO_ROOT / "src"),
        "--collect-submodules",
        "bklms_downloader",
        "--collect-all",
        "customtkinter",
        "--hidden-import",
        "markdownify",
        "--hidden-import",
        "pypdf",
        "--hidden-import",
        "pptx",
        "--collect-all",
        "selenium",
        "--add-data",
        f"{AI_TOOL}{data_separator}tools",
        "--icon",
        str(icon_path),
        str(REPO_ROOT / "app.py"),
    ]


def main() -> int:
    arguments = pyinstaller_arguments()
    icon_index = arguments.index("--icon") + 1
    icon_path = Path(arguments[icon_index])
    if not icon_path.is_file():
        raise SystemExit(f"Required application icon is missing: {icon_path}")
    if not AI_TOOL.is_file():
        raise SystemExit(f"Required AI preparation tool is missing: {AI_TOOL}")

    # Imported lazily so tests and basic source startup do not require the
    # development-only PyInstaller dependency.
    from PyInstaller.__main__ import run

    os.chdir(REPO_ROOT)
    run(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
