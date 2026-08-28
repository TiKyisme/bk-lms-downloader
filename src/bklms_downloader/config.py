from pathlib import Path

LMS_BASE = "https://lms.hcmut.edu.vn"
LMS_HOST = "lms.hcmut.edu.vn"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "BK_LMS_Data"
PAGE_TIMEOUT = 60
# Kept for authenticated course discovery.  Crawler requests use the
# phase-specific limits below so one dead resource cannot stall a whole batch.
REQUEST_TIMEOUT = 90
MAX_REQUEST_ATTEMPTS = 3
REQUEST_RETRY_BACKOFF = 0.4

# A Moodle page or file must establish its HTTP response promptly.  The read
# timeout is an inactivity timeout; a separate total deadline covers retries.
REQUEST_CONNECT_TIMEOUT = 8
REQUEST_READ_TIMEOUT = 20
RESOURCE_OPEN_DEADLINE = 45
TITLE_LOOKUP_DEADLINE = 12

# HTML pages are small enough to have a short complete-body deadline.  File
# transfers use a size-aware deadline instead, so a large lecture PDF that is
# actively moving is not mistaken for a stalled page.
HTML_RESPONSE_DEADLINE = 60
STREAM_MIN_TOTAL_TIMEOUT = 120
STREAM_UNKNOWN_TOTAL_TIMEOUT = 30 * 60
STREAM_SECONDS_PER_MIB = 30
STREAM_MAX_TOTAL_TIMEOUT = 4 * 60 * 60
STREAM_HEARTBEAT_INTERVAL = 2

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
