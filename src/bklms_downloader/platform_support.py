"""Small platform boundaries for the desktop application and release assets."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Callable


APP_NAME = "BK-LMS-Downloader"


def user_config_dir(
    *,
    platform_name: str | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the conventional per-user configuration directory for this OS."""
    name = platform_name if platform_name is not None else sys.platform
    env = environment if environment is not None else os.environ
    user_home = home if home is not None else Path.home()
    if name.startswith("win"):
        return Path(env.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / APP_NAME
    if name == "darwin":
        return user_home / "Library" / "Application Support" / APP_NAME
    return Path(env.get("XDG_CONFIG_HOME", str(user_home / ".config"))) / APP_NAME


def file_manager_command(path: Path | str, *, platform_name: str | None = None) -> list[str] | None:
    """Return the native folder-opening command, or ``None`` for Windows."""
    name = platform_name if platform_name is not None else sys.platform
    rendered = str(Path(path))
    if name.startswith("win"):
        return None
    if name == "darwin":
        return ["open", rendered]
    return ["xdg-open", rendered]


def open_in_file_manager(
    path: Path | str,
    *,
    platform_name: str | None = None,
    windows_opener: Callable[[str], object] | None = None,
    process_launcher: Callable[[list[str]], object] | None = None,
) -> None:
    """Open a local folder using the platform's standard file manager."""
    target = str(Path(path))
    name = platform_name if platform_name is not None else sys.platform
    if name.startswith("win"):
        opener = windows_opener if windows_opener is not None else os.startfile  # type: ignore[attr-defined]
        opener(target)
        return
    command = file_manager_command(target, platform_name=name)
    launcher = process_launcher if process_launcher is not None else subprocess.Popen
    launcher(command or ["xdg-open", target])


def preferred_release_asset_names(
    *,
    platform_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, ...]:
    """Order release assets for the current operating system and CPU."""
    name = platform_name if platform_name is not None else sys.platform
    cpu = (machine if machine is not None else platform.machine()).lower()
    if name == "darwin":
        architecture = "arm64" if cpu in {"arm64", "aarch64"} else "x64"
        return (f"BK-LMS-Downloader-macOS-{architecture}.dmg",)
    if name.startswith("win"):
        return ("BK-LMS-Downloader-Windows.exe", "BK-LMS-Downloader.exe")
    return ()
