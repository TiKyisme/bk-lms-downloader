#!/usr/bin/env python3
"""Read-only size audit for a generated AI Study Pack directory or ZIP."""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def category(name: str) -> str:
    parts = Path(name).parts
    if name.startswith("sources/past_exams/"):
        return "historical exams"
    if parts and parts[0] == "sources":
        return "retained original sources"
    if parts and parts[0] == "documents":
        return "normalized documents"
    if parts and parts[0] == "chunks":
        return "retrieval chunks"
    if parts and parts[0] == "meta":
        return "metadata"
    if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return "images"
    return "control/navigation"


def audit(path: Path) -> None:
    files: list[tuple[str, int, bytes | None, int]] = []
    zip_size = path.stat().st_size if path.is_file() else 0
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    files.append((info.filename, info.file_size, archive.read(info), info.compress_size))
    else:
        for item in path.rglob("*"):
            if item.is_file():
                files.append((item.relative_to(path).as_posix(), item.stat().st_size, item.read_bytes(), item.stat().st_size))
    by_category = Counter()
    by_extension = Counter()
    duplicates: dict[str, list[str]] = defaultdict(list)
    for name, size, payload, _compressed in files:
        by_category[category(name)] += size
        by_extension[Path(name).suffix.lower() or "[none]"] += size
        duplicates[hashlib.sha256(payload or b"").hexdigest()].append(name)
    total = sum(size for _, size, _, _ in files)
    print(f"TOTAL\n- Uncompressed: {total:,} bytes\n- ZIP: {zip_size:,} bytes")
    print("\nBY CATEGORY")
    for name, size in by_category.most_common(): print(f"- {name}: {size:,} bytes")
    print("\nBY EXTENSION")
    for name, size in by_extension.most_common(): print(f"- {name}: {size:,} bytes")
    print("\nTOP FILES")
    for index, (name, size, _, compressed) in enumerate(sorted(files, key=lambda item: item[1], reverse=True)[:30], 1):
        ratio = (compressed / size) if size else 1
        print(f"{index}. {name}: {size:,} bytes (stored ratio {ratio:.2f})")
    print("\nDUPLICATES")
    found = False
    for digest, names in duplicates.items():
        if len(names) > 1:
            found = True; print(f"- {digest[:12]}: " + " | ".join(names))
    if not found: print("- None")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit a local AI Study Pack without sending its contents anywhere.")
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    audit(args.pack.expanduser().resolve())
