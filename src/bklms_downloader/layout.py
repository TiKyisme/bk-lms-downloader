from __future__ import annotations

import re
import unicodedata


BUCKETS = {
    "course_info": "01_Thông tin môn học",
    "lectures": "02_Bài giảng",
    "labs": "03_Lab",
    "assignments": "04_Bài tập",
    "references": "05_Tài liệu tham khảo",
    "other": "06_Khác",
}


def _fold(value: str) -> str:
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[_\-–—]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def bucket_key_for_section(title: str) -> str:
    """Map a Moodle section title into a small student-friendly bucket."""
    text = _fold(title)

    if re.search(r"\b(lab|laboratory|practical|thuc hanh)\b", text):
        return "labs"

    if re.search(
        r"\b(assignment|homework|exercise|project|report|bai tap|btl|do an)\b",
        text,
    ):
        return "assignments"

    if re.search(
        r"\b(textbook|reference|references|book|books|tai lieu tham khao|"
        r"reading|readings)\b",
        text,
    ):
        return "references"

    if re.search(
        r"\b(chapter|lecture|slide|slides|week|tuan|chuong|bai giang|"
        r"lesson|module|content|contents)\b",
        text,
    ):
        return "lectures"

    if re.search(
        r"\b(chung|general|announcement|announcements|overview|syllabus|"
        r"course syllabus|course information|course info|description|grading|"
        r"gioi thieu|thong tin mon hoc|final exam|thi cuoi ky|exam info)\b",
        text,
    ):
        return "course_info"

    return "other"


def bucket_name_for_section(title: str) -> str:
    return BUCKETS[bucket_key_for_section(title)]


def context_prefix(section_title: str, activity_title: str | None = None) -> str:
    """Build a readable filename prefix while keeping the folder tree flat."""
    section = re.sub(r"\s+", " ", (section_title or "").strip())
    activity = re.sub(r"\s+", " ", (activity_title or "").strip())

    if activity and _fold(activity) != _fold(section):
        return f"{section} - {activity} - "
    if section:
        return f"{section} - "
    if activity:
        return f"{activity} - "
    return ""
