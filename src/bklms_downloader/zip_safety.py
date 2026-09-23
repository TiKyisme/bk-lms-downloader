"""Safe ZIP extraction shared by pack refresh and incremental preparation."""
from __future__ import annotations

import zipfile
from pathlib import Path


def safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    root = Path(destination).resolve()
    for member in archive.infolist():
        target = (root / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError("ZIP member escapes extraction workspace")
    archive.extractall(root)
