import importlib.util
from pathlib import Path


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_desktop.py"
SPEC = importlib.util.spec_from_file_location("build_desktop", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
build_desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_desktop)


def option_value(arguments: list[str], option: str) -> str:
    return arguments[arguments.index(option) + 1]


def test_windows_packaging_uses_branded_ico_and_onefile_asset_separator():
    arguments = build_desktop.pyinstaller_arguments("win32")

    assert build_desktop.WINDOWS_ICON.is_file()
    assert "--onefile" in arguments
    assert option_value(arguments, "--name") == "BK-LMS-Downloader"
    assert option_value(arguments, "--icon").endswith("BK-LMS-Downloader-icon-blue.ico")
    assert ";tools" in option_value(arguments, "--add-data")


def test_macos_packaging_uses_clickable_app_name_icns_and_unix_separator():
    arguments = build_desktop.pyinstaller_arguments("darwin")

    assert "--onefile" not in arguments
    assert option_value(arguments, "--name") == "BK-LMS Downloader"
    assert option_value(arguments, "--icon").endswith("build\\BK-LMS-Downloader.icns") or option_value(
        arguments, "--icon"
    ).endswith("build/BK-LMS-Downloader.icns")
    assert ":tools" in option_value(arguments, "--add-data")


def test_both_platforms_bundle_current_ai_and_gui_dependencies():
    for platform_name in ("win32", "darwin"):
        rendered = " ".join(build_desktop.pyinstaller_arguments(platform_name))
        assert "bklms_downloader" in rendered
        assert "customtkinter" in rendered
        assert "markdownify" in rendered
        assert "pypdf" in rendered
        assert "pptx" in rendered
        assert "selenium" in rendered
