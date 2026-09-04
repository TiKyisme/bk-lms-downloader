#!/usr/bin/env python3
"""Validate authoritative source, tag, and optional Microsoft Store versions."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bklms_downloader.versioning import parse_semantic_version, validate_msix_version


def source_versions() -> tuple[str, str]:
    project_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(
        r'^version\s*=\s*["\']([^"\']+)["\']',
        project_text,
        flags=re.MULTILINE,
    )
    if project_match is None:
        raise ValueError("Could not find project version in pyproject.toml")
    project_version = project_match.group(1)
    init_text = (SRC_ROOT / "bklms_downloader" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, flags=re.MULTILINE)
    if match is None:
        raise ValueError("Could not find __version__ in package __init__.py")
    return project_version, match.group(1)


def validate_versions(*, tag: str | None = None, msix_version: str | None = None) -> str:
    project_version, package_version = source_versions()
    parse_semantic_version(project_version)
    if package_version != project_version:
        raise ValueError(
            f"Version mismatch: pyproject.toml={project_version}, __init__.py={package_version}"
        )
    if tag and tag.lstrip("vV") != project_version:
        raise ValueError(f"Tag {tag} does not match source version {project_version}")
    if msix_version:
        validate_msix_version(project_version, msix_version)
    return project_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--msix-version")
    args = parser.parse_args()
    version = validate_versions(tag=args.tag, msix_version=args.msix_version)
    print(f"Version validation OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
