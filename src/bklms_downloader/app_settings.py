from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_OUTPUT
from .app_logging import get_logger
from .platform_support import user_config_dir


SCHEMA_VERSION = 1
LOG = get_logger(__name__)


def default_settings_path() -> Path:
    """Return the per-user UI settings file without using the repository."""
    return user_config_dir() / "settings.json"


class AppSettings:
    """Small, credential-free preferences store for the desktop UI."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        default_output: Path | str = DEFAULT_OUTPUT,
    ):
        self.path = Path(path) if path is not None else default_settings_path()
        self.default_output = self.normalize_path(default_output)
        self.last_output_dir = self.default_output
        self.load()

    def load(self) -> str:
        """Load the harmless setting, safely falling back after any corruption."""
        self.last_output_dir = self.default_output
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._backup_corrupt_file()
            return self.last_output_dir
        except (OSError, UnicodeDecodeError):
            return self.last_output_dir

        value = payload.get("last_output_dir") if isinstance(payload, dict) else None
        if isinstance(value, str) and value.strip():
            self.last_output_dir = self.normalize_path(value)
        return self.last_output_dir

    def set_last_output_dir(self, output: Path | str) -> str:
        self.last_output_dir = self.normalize_path(output)
        self.save()
        return self.last_output_dir

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "last_output_dir": self.last_output_dir,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.stem}-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def normalize_path(value: Path | str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Thư mục lưu không được để trống.")
        return str(Path(raw).expanduser())

    # Kept as a private alias for older callers while new UI flows use the
    # public normalization boundary explicitly.
    _normalise_path = normalize_path

    def _backup_corrupt_file(self) -> None:
        if not self.path.is_file():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        try:
            shutil.copy2(self.path, backup)
            LOG.warning("Backed up corrupt settings file to %s", backup)
        except OSError:
            pass
