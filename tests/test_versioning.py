import importlib.util
from pathlib import Path

import pytest

from bklms_downloader.versioning import parse_semantic_version, validate_msix_version


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "validate_versions.py"
SPEC = importlib.util.spec_from_file_location("validate_versions", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_versions_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_versions_tool)


def test_semantic_and_msix_versions_require_expected_shapes():
    assert parse_semantic_version("1.1.2") == (1, 1, 2)
    assert validate_msix_version("1.1.2", "1.1.2.0") == (1, 1, 2, 0)
    with pytest.raises(ValueError, match="four numeric components"):
        validate_msix_version("1.1.2", "1.1.2")
    with pytest.raises(ValueError, match="revision.*must be 0"):
        validate_msix_version("1.1.2", "1.1.2.1")
    with pytest.raises(ValueError, match="must match"):
        validate_msix_version("1.1.2", "1.1.1.0")


def test_source_version_checker_rejects_mismatched_tag():
    current, package = validate_versions_tool.source_versions()
    assert current == package
    assert validate_versions_tool.validate_versions(tag=f"v{current}") == current
    with pytest.raises(ValueError, match="does not match"):
        validate_versions_tool.validate_versions(tag="v9.9.9")
