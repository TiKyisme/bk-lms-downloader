#!/usr/bin/env python3
"""Repair filenames previously downloaded with UTF-8/Latin-1 mojibake.

Default is dry-run. Add --apply to rename files/folders in place.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bklms_downloader.utils import repair_mojibake, safe_name  # noqa: E402


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair mojibake Vietnamese filenames in an existing download tree.")
    parser.add_argument("path", type=Path, help="Course/output folder to scan")
    parser.add_argument("--apply", action="store_true", help="Actually rename. Without this flag the tool only previews changes.")
    args = parser.parse_args()

    root = args.path.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        parser.error(f"Folder does not exist: {root}")

    # Deepest first so renaming a directory does not invalidate child paths.
    items = sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    changes = 0

    for item in items:
        fixed = safe_name(repair_mojibake(item.name), 240)
        if fixed == item.name:
            continue
        destination = unique_destination(item.with_name(fixed))
        changes += 1
        print(f"{item.name}\n  -> {destination.name}")
        if args.apply:
            item.rename(destination)

    if changes == 0:
        print("Không tìm thấy tên file/folder bị lỗi encoding.")
    elif args.apply:
        print(f"\nĐã sửa {changes} tên file/folder.")
    else:
        print(f"\nTìm thấy {changes} tên có thể sửa. Chạy lại với --apply để đổi tên thật.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
