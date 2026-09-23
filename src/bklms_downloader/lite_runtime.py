"""Packaged-runtime dependency check for safe Lite retention."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


REQUIRED_MODULES = ("fitz", "PIL", "pptx")


def lite_runtime_diagnostics() -> str:
    modules = list(REQUIRED_MODULES)
    if sys.platform.startswith("win"):
        modules.append("win32com.client")
    lines = []
    for module in modules:
        try:
            imported = importlib.import_module(module)
            lines.append(f"{module}: IMPORT OK ({getattr(imported, '__file__', None)!r})")
        except Exception as exc:
            lines.append(f"{module}: IMPORT FAILED: {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def run_lite_runtime_self_test() -> int:
    report = lite_runtime_diagnostics()
    failure = "IMPORT FAILED" in report
    Path("lite-runtime-self-test.log").write_text(report + "\n", encoding="utf-8")
    return 1 if failure else 0
