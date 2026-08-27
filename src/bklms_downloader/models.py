from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Activity:
    order: int
    name: str
    url: str
    mod_type: str


@dataclass
class Section:
    index: int
    title: str
    node_html: str
    activities: list[Activity]


@dataclass
class Course:
    """A locally saved BK-LMS course.  It never contains authentication data."""

    id: str
    url: str
    output: str
    name: str = ""
    code: str = ""
    selected: bool = True
    last_sync: Optional[str] = None
    last_status: str = "never"
    last_downloaded: int = 0
    last_skipped: int = 0
    last_errors: int = 0

    @property
    def output_path(self) -> Path:
        return Path(self.output).expanduser()

    @property
    def display_name(self) -> str:
        return self.name or "Chưa nhận diện"

    @classmethod
    def from_dict(cls, value: dict) -> "Course":
        """Build a safe course value from the small on-disk JSON schema."""
        return cls(
            id=str(value.get("id", "")).strip(),
            url=str(value.get("url", "")).strip(),
            output=str(value.get("output", "")).strip(),
            name=str(value.get("name", "")).strip(),
            code=str(value.get("code", "")).strip().upper(),
            selected=bool(value.get("selected", True)),
            last_sync=(
                str(value["last_sync"]).strip()
                if value.get("last_sync")
                else None
            ),
            last_status=str(value.get("last_status", "never")).strip() or "never",
            last_downloaded=_non_negative_int(value.get("last_downloaded")),
            last_skipped=_non_negative_int(value.get("last_skipped")),
            last_errors=_non_negative_int(value.get("last_errors")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "code": self.code,
            "output": self.output,
            "selected": self.selected,
            "last_sync": self.last_sync,
            "last_status": self.last_status,
            "last_downloaded": self.last_downloaded,
            "last_skipped": self.last_skipped,
            "last_errors": self.last_errors,
        }


def checked_courses(courses: Iterable[Course]) -> list[Course]:
    """Return checkbox-selected courses without mutating their shared state."""
    return [course for course in courses if course.selected]


@dataclass
class CourseSyncResult:
    """Structured outcome for one course sync, independent of GUI text."""

    course_id: str
    course_url: str
    name: str
    output: Optional[Path]
    downloaded: int = 0
    skipped: int = 0
    skipped_video: int = 0
    pages_saved: int = 0
    errors: int = 0
    status: str = "success"
    error_message: Optional[str] = None


@dataclass
class SyncBatchResult:
    """Aggregated result for a sequential Sync selected / Sync all run."""

    results: list[CourseSyncResult]
    authentication_error: bool = False

    @property
    def downloaded(self) -> int:
        return sum(result.downloaded for result in self.results)

    @property
    def skipped(self) -> int:
        return sum(result.skipped for result in self.results)

    @property
    def skipped_video(self) -> int:
        return sum(result.skipped_video for result in self.results)

    @property
    def errors(self) -> int:
        return sum(result.errors for result in self.results)

    @property
    def synced_courses(self) -> int:
        return sum(result.status != "error" for result in self.results)


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
