from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


GITHUB_RELEASES_API = "https://api.github.com/repos/TiKyisme/bk-lms-downloader/releases"
UPDATE_TIMEOUT = 5


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    download_url: str | None
    release_notes: str
    update_available: bool


def parse_version(value: str) -> tuple[int, int, int] | None:
    """Parse only stable MAJOR.MINOR.PATCH release tags."""
    normalized = (value or "").strip().lstrip("vV")
    parts = normalized.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    return bool(candidate_version and current_version and candidate_version > current_version)


class UpdateChecker:
    """Read GitHub's public release metadata without changing application state."""

    def __init__(
        self,
        current_version: str,
        *,
        api_url: str = GITHUB_RELEASES_API,
        session: requests.Session | None = None,
        timeout: int = UPDATE_TIMEOUT,
    ):
        self.current_version = current_version
        self.api_url = api_url
        self.session = session or requests.Session()
        self.timeout = timeout

    def check(self) -> UpdateInfo | None:
        """Return a newer stable release, or ``None`` for offline/no-update cases."""
        try:
            response = self.session.get(
                self.api_url,
                timeout=self.timeout,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError):
            return None

        latest = self._latest_stable_release(payload)
        if latest is None:
            return None

        tag = str(latest.get("tag_name", ""))
        if not is_newer_version(tag, self.current_version):
            return None

        release_url = str(latest.get("html_url", "")).strip()
        if not release_url:
            return None
        return UpdateInfo(
            current_version=self.current_version,
            latest_version=tag.lstrip("vV"),
            release_url=release_url,
            download_url=self._exe_download_url(latest),
            release_notes=str(latest.get("body", "")).strip(),
            update_available=True,
        )

    @staticmethod
    def _latest_stable_release(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, list):
            return None
        stable: list[dict[str, Any]] = []
        for release in payload:
            if not isinstance(release, dict):
                continue
            if release.get("draft") or release.get("prerelease"):
                continue
            if parse_version(str(release.get("tag_name", ""))) is None:
                continue
            stable.append(release)
        if not stable:
            return None
        return max(stable, key=lambda release: parse_version(str(release["tag_name"])) or (0, 0, 0))

    @staticmethod
    def _exe_download_url(release: dict[str, Any]) -> str | None:
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            return None
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).lower()
            url = str(asset.get("browser_download_url", "")).strip()
            if name.endswith(".exe") and url:
                return url
        return None
