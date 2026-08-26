from pathlib import Path

LMS_BASE = "https://lms.hcmut.edu.vn"
LMS_HOST = "lms.hcmut.edu.vn"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "BK_LMS_Data"
PAGE_TIMEOUT = 60
REQUEST_TIMEOUT = 90

FILE_URL_MARKERS = ("/pluginfile.php/", "/draftfile.php/")
INTERACTIVE_MODS = {
    "forum", "assign", "quiz", "choice", "feedback", "workshop",
    "attendance", "chat", "survey", "questionnaire", "scheduler",
}
DEEP_MODS = {"page", "folder", "book", "url", "lesson", "resource"}
MEDIA_TAG_ATTRS = {
    "img": "src",
    "source": "src",
    "video": "src",
    "audio": "src",
    "track": "src",
}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
