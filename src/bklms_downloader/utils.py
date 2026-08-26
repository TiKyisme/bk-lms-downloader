from __future__ import annotations

import json
import mimetypes
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, unquote, unquote_to_bytes, urlparse, urlunparse

import requests

from .config import FILE_URL_MARKERS, LMS_HOST, VIDEO_EXTENSIONS


def clean_text(value: str) -> str:
    value = (value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def repair_mojibake(value: str) -> str:
    """Repair the common UTF-8-as-Latin-1 filename corruption seen on Moodle.

    HTTP headers are historically decoded as ISO-8859-1 by clients. Some Moodle/
    web-server stacks nevertheless place UTF-8 bytes directly in the legacy
    ``filename=`` parameter. ``requests`` then exposes names such as
    ``CHÆ¯Æ NG`` instead of ``CHƯƠNG``. This function only accepts a repaired
    candidate when the original string looks suspicious and the UTF-8 decode
    succeeds, so normal Vietnamese Unicode names are left untouched.
    """
    if not value:
        return value

    suspicious = (
        "Ã", "Â", "Æ", "Ä", "áº", "á»", "â€", "ðŸ",
        "\x80", "\x81", "\x82", "\x83", "\x84", "\x85", "\x86", "\x87",
        "\x88", "\x89", "\x8a", "\x8b", "\x8c", "\x8d", "\x8e", "\x8f",
        "\x90", "\x91", "\x92", "\x93", "\x94", "\x95", "\x96", "\x97",
        "\x98", "\x99", "\x9a", "\x9b", "\x9c", "\x9d", "\x9e", "\x9f",
    )
    if not any(marker in value for marker in suspicious):
        return unicodedata.normalize("NFC", value)

    candidates = [value]

    # The most common BK-LMS/Moodle case: UTF-8 bytes decoded as ISO-8859-1.
    try:
        candidates.append(value.encode("latin-1").decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # A few proxies/browsers expose CP1252 punctuation instead of C1 controls.
    try:
        candidates.append(value.encode("cp1252").decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    def badness(text: str) -> int:
        score = text.count("\ufffd") * 100
        score += sum(text.count(x) * 8 for x in ("Ã", "Â", "Æ", "Ä", "áº", "á»", "â€", "ðŸ"))
        score += sum(4 for ch in text if 0x80 <= ord(ch) <= 0x9F)
        return score

    best = min(candidates, key=badness)
    return unicodedata.normalize("NFC", best)


def safe_name(value: str, max_len: int = 130) -> str:
    # Repair before whitespace cleanup: mojibake for some Vietnamese letters can
    # contain U+00A0, which clean_text would otherwise turn into a normal space.
    value = clean_text(repair_mojibake(value or ""))
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


def normalized_course_url(url: str) -> str:
    """Return the stable Moodle course URL used for local duplicate detection."""
    parsed = urlparse(url.strip())
    course_ids = parse_qs(parsed.query).get("id", [])
    if not course_ids:
        return normalize_url(url)
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            "",
            f"id={course_ids[0]}",
            "",
        )
    )


def extract_course_code(name: str) -> str | None:
    """Extract a conservative HCMUT course code such as ``CO3094`` or ``GE1013``."""
    match = re.search(r"(?<![A-Z0-9])([A-Z]{2,4}\d{3,6})(?![A-Z0-9])", name or "", re.I)
    return match.group(1).upper() if match else None


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


def _decode_rfc5987_filename(raw: str) -> str:
    """Decode filename*=charset''percent-encoded-value."""
    raw = raw.strip().strip('"')
    m = re.match(r"(?i)^([^']*)'[^']*'(.*)$", raw)
    if not m:
        return repair_mojibake(unquote(raw))

    charset = (m.group(1) or "utf-8").strip() or "utf-8"
    encoded = m.group(2)
    try:
        return unicodedata.normalize("NFC", unquote_to_bytes(encoded).decode(charset, errors="strict"))
    except (LookupError, UnicodeDecodeError):
        return repair_mojibake(unquote(encoded))


def filename_from_response(response: requests.Response, fallback: str) -> str:
    cd = response.headers.get("Content-Disposition", "")

    # RFC 5987 / RFC 6266 form, preferred when available.
    m = re.search(r"filename\*\s*=\s*([^;]+)", cd, flags=re.I)
    if m:
        return safe_name(_decode_rfc5987_filename(m.group(1)), 180)

    # Legacy filename= is where BK-LMS may expose UTF-8 bytes as Latin-1 text.
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, flags=re.I)
    if m:
        return safe_name(repair_mojibake(m.group(1)), 180)

    m = re.search(r"filename\s*=\s*([^;]+)", cd, flags=re.I)
    if m:
        return safe_name(repair_mojibake(m.group(1).strip().strip('"')), 180)

    path_name = repair_mojibake(unquote(Path(urlparse(response.url).path).name))
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
