"""Small, explicit host boundaries for public Coursewave resources."""
from __future__ import annotations

from urllib.parse import urlparse


GOOGLE_REDIRECT_HOSTS = {"google.com", "www.google.com"}
GOOGLE_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}


def normalized_hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").rstrip(".").casefold()
    except ValueError:
        return ""


def host_is_allowed(url: str, allowed: set[str], *, allow_subdomains: bool = False) -> bool:
    host = normalized_hostname(url)
    return bool(host) and any(host == item or (allow_subdomains and host.endswith("." + item)) for item in allowed)


def is_google_redirect_url(url: str) -> bool:
    return host_is_allowed(url, GOOGLE_REDIRECT_HOSTS)


def is_public_drive_url(url: str) -> bool:
    return host_is_allowed(url, GOOGLE_DRIVE_HOSTS)
