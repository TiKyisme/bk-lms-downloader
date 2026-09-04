"""Release and Microsoft Store version validation rules."""

from __future__ import annotations

import re


SEMANTIC_VERSION_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
MSIX_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)\.(?P<revision>0|[1-9]\d*)$"
)


def parse_semantic_version(value: str) -> tuple[int, int, int]:
    match = SEMANTIC_VERSION_RE.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Application version must be MAJOR.MINOR.PATCH: {value}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))  # type: ignore[return-value]


def validate_msix_version(application_version: str, package_version: str) -> tuple[int, int, int, int]:
    application = parse_semantic_version(application_version)
    match = MSIX_VERSION_RE.fullmatch(str(package_version).strip())
    if match is None:
        raise ValueError(f"MSIX version must have four numeric components: {package_version}")
    package = tuple(
        int(match.group(name))
        for name in ("major", "minor", "patch", "revision")
    )
    if package[:3] != application:
        raise ValueError(
            f"MSIX version {package_version} must match application version {application_version}."
        )
    if package[3] != 0:
        raise ValueError("Microsoft Store package revision (fourth component) must be 0.")
    return package  # type: ignore[return-value]
