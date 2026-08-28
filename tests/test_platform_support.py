from pathlib import Path

from bklms_downloader.platform_support import (
    file_manager_command,
    open_in_file_manager,
    preferred_release_asset_names,
    user_config_dir,
)


def test_user_config_dir_uses_native_platform_conventions(tmp_path: Path):
    assert user_config_dir(
        platform_name="win32",
        environment={"APPDATA": r"C:\Users\Student\AppData\Roaming"},
        home=tmp_path,
    ) == Path(r"C:\Users\Student\AppData\Roaming") / "BK-LMS-Downloader"
    assert user_config_dir(platform_name="darwin", home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "BK-LMS-Downloader"
    )
    assert user_config_dir(
        platform_name="linux",
        environment={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
        home=tmp_path,
    ) == tmp_path / "xdg" / "BK-LMS-Downloader"


def test_file_manager_abstraction_uses_open_on_macos_and_startfile_on_windows(tmp_path: Path):
    target = tmp_path / "course"
    assert file_manager_command(target, platform_name="darwin") == ["open", str(target)]
    assert file_manager_command(target, platform_name="linux") == ["xdg-open", str(target)]
    assert file_manager_command(target, platform_name="win32") is None

    opened = []
    open_in_file_manager(target, platform_name="win32", windows_opener=opened.append)
    assert opened == [str(target)]


def test_release_assets_follow_platform_and_mac_architecture():
    assert preferred_release_asset_names(platform_name="win32") == (
        "BK-LMS-Downloader-Windows.exe",
        "BK-LMS-Downloader.exe",
    )
    assert preferred_release_asset_names(platform_name="darwin", machine="arm64") == (
        "BK-LMS-Downloader-macOS-arm64.dmg",
    )
    assert preferred_release_asset_names(platform_name="darwin", machine="x86_64") == (
        "BK-LMS-Downloader-macOS-x64.dmg",
    )
