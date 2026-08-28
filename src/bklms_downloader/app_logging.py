from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .platform_support import user_config_dir


APP_NAME = "BK-LMS-Downloader"


def default_log_path() -> Path:
    return user_config_dir() / "logs" / "app.log"


def redact_sensitive_text(value: str) -> str:
    """Remove credentials and common session values before they reach disk."""
    text = str(value)
    text = re.sub(
        r"(?i)\b(cookie|set-cookie|authorization)\s*[:=]\s*[^\r\n]+",
        r"\1: [REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)\b(moodlesession[a-z0-9_]*|sessionid|sesskey|access_token|token)\s*=\s*[^\s;&,]+",
        r"\1=[REDACTED]",
        text,
    )


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str = "bklms_downloader") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        path = default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger
