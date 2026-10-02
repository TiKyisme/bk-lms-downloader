"""Safe, relative-path inventory for one downloaded BK-LMS course."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re


TEXT_EXTS = {".txt", ".md"}
HTML_EXTS = {".html", ".htm"}
PDF_EXTS = {".pdf"}
PPT_EXTS = {".pptx"}
WORD_EXTS = {".docx"}
SPREADSHEET_EXTS = {".xlsx", ".xlsm"}
CSV_EXTS = {".csv"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
SUBTITLE_EXTS = {".srt", ".vtt"}
URL_EXTS = {".url"}
JSON_EXTS = {".json"}

SUPPORTED_EXTENSIONS = (
    TEXT_EXTS | HTML_EXTS | PDF_EXTS | PPT_EXTS | WORD_EXTS
    | SPREADSHEET_EXTS | CSV_EXTS | VIDEO_EXTS | AUDIO_EXTS
    | SUBTITLE_EXTS | URL_EXTS
)
LECTURER_MATERIAL_EXTENSIONS = (
    TEXT_EXTS | HTML_EXTS | PDF_EXTS | PPT_EXTS | WORD_EXTS
    | SPREADSHEET_EXTS | CSV_EXTS | VIDEO_EXTS | AUDIO_EXTS | SUBTITLE_EXTS
)
SKIP_DIR_NAMES = {
    "AI_Knowledge",
    "__MACOSX",
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "duylms_forum_debug",
}
STUDY_PACK_SUFFIXES = (" - AI Study Pack.zip", "_AI_Study_Pack.zip")
DOWNLOADER_METADATA_RELATIVE_PATHS = {
    "_meta/course_structure.json",
    "_meta/download_manifest.json",
    "_meta/stats.json",
    "_meta/_course_structure.json",
    "_meta/_download_manifest.json",
    "_meta/_stats.json",
}
_SENSITIVE_PATH_VALUE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|access[_-]?token|refresh[_-]?token|token|sessionid|sesskey)([=:])[^/\\]*"
)


@dataclass(frozen=True)
class SourceInventory:
    total_source_files: int
    total_input_bytes: int
    extension_counts: dict[str, int]
    supported_files: int
    unsupported_files: int
    lecturer_material_candidates: int
    downloader_metadata_files: int
    unsupported_relative_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def safe_relative_diagnostic_path(value: str) -> str:
    """Redact credential-like values from a relative filename before display."""
    normalized = str(value).replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
    return _SENSITIVE_PATH_VALUE.sub(r"\1\2[redacted]", normalized)


def iter_course_source_files(root: Path) -> list[Path]:
    """Return regular files under one root without traversing generated trees or links."""
    root = Path(root).expanduser().resolve()
    results: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        subdirectories[:] = [
            name for name in subdirectories
            if name not in SKIP_DIR_NAMES and not (current / name).is_symlink()
        ]
        for filename in filenames:
            path = current / filename
            if path.name.endswith(STUDY_PACK_SUFFIXES) or not path.is_file():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            results.append(path)
    return sorted(results, key=lambda item: item.as_posix().casefold())


def is_downloader_metadata(path: Path, root: Path) -> bool:
    try:
        relative = Path(path).relative_to(Path(root)).as_posix().casefold()
    except ValueError:
        return False
    if relative in DOWNLOADER_METADATA_RELATIVE_PATHS:
        return True
    return Path(relative).name in {"_course_structure.json", "_download_manifest.json", "_stats.json"}


def inventory_course_sources(root: Path) -> SourceInventory:
    """Count files and types only; never include absolute paths or file contents."""
    root = Path(root).expanduser().resolve()
    files = iter_course_source_files(root)
    extensions: Counter[str] = Counter()
    supported = unsupported = lecturer = metadata = total_bytes = 0
    unsupported_paths: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        extension = path.suffix.casefold() or "[no extension]"
        extensions[extension] += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        if is_downloader_metadata(path, root):
            metadata += 1
            continue
        if extension in SUPPORTED_EXTENSIONS:
            supported += 1
        else:
            unsupported += 1
            unsupported_paths.append(safe_relative_diagnostic_path(relative))
        if extension in LECTURER_MATERIAL_EXTENSIONS:
            lecturer += 1
    return SourceInventory(
        total_source_files=len(files),
        total_input_bytes=total_bytes,
        extension_counts=dict(sorted(extensions.items())),
        supported_files=supported,
        unsupported_files=unsupported,
        lecturer_material_candidates=lecturer,
        downloader_metadata_files=metadata,
        unsupported_relative_paths=tuple(unsupported_paths),
    )
