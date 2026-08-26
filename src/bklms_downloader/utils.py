from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import requests

from .config import FILE_URL_MARKERS, LMS_HOST, VIDEO_EXTENSIONS


def clean_text(value: str) -> str:
    value = (value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def safe_name(value: str, max_len: int = 130) -> str:
    value = clean_text(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).rstrip(" .")
    if not value:
        value = "untitled"

    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if value.upper() in reserved:
        value = "_" + value

    return value[:max_len].rstrip(" .") or "untitled"


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc.lower(), p.path, p.params, p.query, ""))
    except Exception:
        return url


def is_same_lms(url: str) -> bool:
    try:
        return urlparse(url).netloc.lower().endswith(LMS_HOST)
    except Exception:
        return False


def is_course_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return (
            p.netloc.lower().endswith(LMS_HOST)
            and p.path.endswith("/course/view.php")
            and bool(parse_qs(p.query).get("id"))
        )
    except Exception:
        return False


def activity_type(url: str) -> str:
    path = urlparse(url).path.lower()
    m = re.search(r"/mod/([^/]+)/", path)
    if m:
        return m.group(1)
    if any(marker in path for marker in FILE_URL_MARKERS):
        return "pluginfile"
    if is_course_url(url):
        return "course"
    return "other"


def is_probably_file_url(url: str) -> bool:
    path = unquote(urlparse(url).path)
    if any(marker in path.lower() for marker in FILE_URL_MARKERS):
        return True
    suffix = Path(path).suffix.lower()
    return suffix in {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".zip", ".rar", ".7z", ".txt", ".csv", ".json", ".xml",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
        ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mp3", ".wav", ".m4a",
        ".py", ".java", ".c", ".cpp", ".h", ".kt", ".ipynb",
    }


def is_video_url(url: str) -> bool:
    return Path(unquote(urlparse(url).path)).suffix.lower() in VIDEO_EXTENSIONS


def is_video_response(response: requests.Response) -> bool:
    ctype = response.headers.get("Content-Type", "").lower()
    if ctype.startswith("video/"):
        return True
    return is_video_url(response.url)


def html_response(response: requests.Response) -> bool:
    ctype = response.headers.get("Content-Type", "").lower()
    return "text/html" in ctype or "application/xhtml+xml" in ctype


def filename_from_response(response: requests.Response, fallback: str) -> str:
    cd = response.headers.get("Content-Disposition", "")

    m = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cd, flags=re.I)
    if m:
        return safe_name(unquote(m.group(1).strip().strip('"')), 180)

    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, flags=re.I)
    if m:
        return safe_name(m.group(1), 180)

    m = re.search(r"filename\s*=\s*([^;]+)", cd, flags=re.I)
    if m:
        return safe_name(m.group(1).strip().strip('"'), 180)

    path_name = unquote(Path(urlparse(response.url).path).name)
    if path_name and "." in path_name:
        return safe_name(path_name, 180)

    ctype = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    ext = mimetypes.guess_extension(ctype) or ""
    return safe_name(fallback, 160) + ext


def write_url_shortcut(path: Path, url: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
    return path


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
