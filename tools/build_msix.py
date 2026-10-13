"""Build an unsigned Store MSIX from a reviewed manifest model and trusted assets.

Run with the build virtual environment's Python on Windows. Historical package
metadata is treated as an identity/branding seed only; extensions are never copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from bklms_downloader.versioning import parse_semantic_version, validate_msix_version
from validate_versions import source_versions, validate_versions

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
NAME = "TiKyisme.BK-LMSDownloader"
PUBLISHER = "CN=73CAA01F-F63A-4EAE-BDD2-53B50789E666"
PUBLISHER_DISPLAY_NAME = "TiKyisme"
DISPLAY_NAME = "BK-LMS Downloader"
DESCRIPTION = "BK-LMS course material downloader for HCMUT students"
APP_ID = "BKLMSDOWNLOADER"
EXE = "BK-LMS-Downloader.exe"
ENTRY_POINT = "Windows.FullTrustApplication"
SELF_TESTS = ("ai", "lite-runtime", "sync", "scroll")
TARGET_DEVICE_FAMILY = "Windows.Desktop"
MIN_VERSION = "10.0.17763.0"
MAX_TESTED_VERSION = "10.0.22000.1"

VISUAL_ATTRIBUTES = (
    "BackgroundColor",
    "DisplayName",
    "Square150x150Logo",
    "Square44x44Logo",
    "Description",
)
TILE_ATTRIBUTES = (
    "Wide310x150Logo",
    "Square310x310Logo",
    "Square71x71Logo",
)
VERSIONED_PACKAGE_PATH = re.compile(
    r"(?i)TiKyisme\.BK-LMSDownloader_\d+\.\d+\.\d+\.\d+_x64__"
)


def safe_name(name: str) -> str:
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name:
        raise ValueError("Unsafe package path")
    return name


def _q(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _one(parent: ET.Element, path: str, description: str) -> ET.Element:
    items = parent.findall(path)
    if len(items) != 1:
        raise ValueError(f"Expected exactly one {description}")
    return items[0]


def _asset_ref(value: str | None, description: str) -> str:
    if not value:
        raise ValueError(f"Missing {description}")
    normalized = safe_name(value)
    if not normalized.startswith("Assets/") or Path(normalized).suffix.lower() not in {".png", ".ico"}:
        raise ValueError(f"Invalid branding asset path for {description}: {value}")
    return normalized


def _manifest_asset_references(root: ET.Element) -> set[str]:
    properties = root.find(_q(FOUNDATION, "Properties"))
    if properties is None:
        raise ValueError("Missing package properties")
    refs = {_asset_ref(properties.findtext(_q(FOUNDATION, "Logo")), "package logo")}
    applications = root.findall(f"{_q(FOUNDATION, 'Applications')}/{_q(FOUNDATION, 'Application')}")
    if len(applications) != 1:
        raise ValueError("Expected one packaged application")
    visual = applications[0].find(_q(UAP, "VisualElements"))
    if visual is None:
        raise ValueError("Missing visual elements")
    for name in VISUAL_ATTRIBUTES:
        if name.endswith("Logo"):
            refs.add(_asset_ref(visual.get(name), name))
    tile = visual.find(_q(UAP, "DefaultTile"))
    if tile is None:
        raise ValueError("Missing default tile")
    for name in TILE_ATTRIBUTES:
        refs.add(_asset_ref(tile.get(name), name))
    return refs


def _validate_launch_policy(root: ET.Element) -> None:
    serialized = ET.tostring(root, encoding="unicode")
    lowered = serialized.casefold()
    if "windowsapps" in lowered:
        raise ValueError("Manifest must not reference WindowsApps paths")
    if VERSIONED_PACKAGE_PATH.search(serialized):
        raise ValueError("Manifest must not reference a version-specific package folder")
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in {"Extensions", "Extension", "Shortcut", "AppExecutionAlias"}:
            raise ValueError(f"Unreviewed launch extension is not allowed: {local_name}")


def inspect_manifest(data: bytes, version: str | None = None) -> ET.Element:
    root = ET.fromstring(data)
    if root.tag != _q(FOUNDATION, "Package"):
        raise ValueError("Unexpected package manifest root")
    _validate_launch_policy(root)

    identity = _one(root, _q(FOUNDATION, "Identity"), "package identity")
    if identity.get("Name") != NAME or identity.get("Publisher") != PUBLISHER:
        raise ValueError("Unexpected Store identity")
    if identity.get("ProcessorArchitecture") != "x64":
        raise ValueError("Only the existing x64 package is supported")
    actual_version = identity.get("Version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.0", actual_version):
        raise ValueError("MSIX version must have four numeric components with revision 0")
    if version and actual_version != version:
        raise ValueError("MSIX version mismatch")

    properties = _one(root, _q(FOUNDATION, "Properties"), "properties")
    if properties.findtext(_q(FOUNDATION, "DisplayName")) != DISPLAY_NAME:
        raise ValueError("Unexpected package display name")
    if properties.findtext(_q(FOUNDATION, "PublisherDisplayName")) != PUBLISHER_DISPLAY_NAME:
        raise ValueError("Unexpected publisher display name")

    dependencies = _one(root, _q(FOUNDATION, "Dependencies"), "dependencies")
    families = dependencies.findall(_q(FOUNDATION, "TargetDeviceFamily"))
    if len(families) != 1 or families[0].get("Name") != TARGET_DEVICE_FAMILY:
        raise ValueError("Unexpected target device family")
    if families[0].get("MinVersion") != MIN_VERSION:
        raise ValueError("Unexpected minimum Windows version")
    if families[0].get("MaxVersionTested") != MAX_TESTED_VERSION:
        raise ValueError("Unexpected tested Windows version")

    applications = _one(root, _q(FOUNDATION, "Applications"), "applications")
    app = _one(applications, _q(FOUNDATION, "Application"), "application")
    if (app.get("Id"), app.get("Executable"), app.get("EntryPoint")) != (APP_ID, EXE, ENTRY_POINT):
        raise ValueError("Unexpected application ID or desktop entry point")
    visual = app.find(_q(UAP, "VisualElements"))
    if visual is None or visual.get("DisplayName") != DISPLAY_NAME:
        raise ValueError("Missing or unexpected visual elements")
    if not visual.get("BackgroundColor") or not visual.get("Description"):
        raise ValueError("Incomplete visual elements")
    if visual.find(_q(UAP, "DefaultTile")) is None:
        raise ValueError("Missing default tile")
    _manifest_asset_references(root)

    capabilities = _one(root, _q(FOUNDATION, "Capabilities"), "capabilities")
    names = [item.get("Name") for item in capabilities]
    if len(capabilities) != 1 or names != ["runFullTrust"]:
        raise ValueError("Unexpected capabilities; only runFullTrust is allowed")
    return root


def create_store_manifest(seed_data: bytes, version: str) -> bytes:
    """Create a new manifest from an allow-listed model; discard seed extensions."""
    seed = ET.fromstring(seed_data)
    identity = _one(seed, _q(FOUNDATION, "Identity"), "seed identity")
    if (identity.get("Name"), identity.get("Publisher"), identity.get("ProcessorArchitecture")) != (
        NAME, PUBLISHER, "x64"
    ):
        raise ValueError("Trusted Store identity is required")
    try:
        seed_version = tuple(int(part) for part in identity.get("Version", "").split("."))
        candidate_version = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise ValueError("Invalid seed or candidate MSIX version") from exc
    if len(seed_version) != 4 or len(candidate_version) != 4 or candidate_version[3] != 0:
        raise ValueError("Seed and candidate must use four-part MSIX versions with revision 0")
    if seed_version >= candidate_version:
        raise ValueError("Candidate must be newer than the identity seed")

    seed_properties = _one(seed, _q(FOUNDATION, "Properties"), "seed properties")
    seed_app = _one(
        _one(seed, _q(FOUNDATION, "Applications"), "seed applications"),
        _q(FOUNDATION, "Application"), "seed application",
    )
    if (seed_app.get("Id"), seed_app.get("Executable"), seed_app.get("EntryPoint")) != (
        APP_ID, EXE, ENTRY_POINT
    ):
        raise ValueError("Unexpected application ID or desktop entry point in seed")
    seed_visual = seed_app.find(_q(UAP, "VisualElements"))
    if seed_visual is None:
        raise ValueError("Seed is missing visual elements")
    seed_tile = seed_visual.find(_q(UAP, "DefaultTile"))
    if seed_tile is None:
        raise ValueError("Seed is missing default tile")

    seed_dependencies = _one(seed, _q(FOUNDATION, "Dependencies"), "seed dependencies")
    seed_family = _one(seed_dependencies, _q(FOUNDATION, "TargetDeviceFamily"), "seed target family")
    if (seed_family.get("Name"), seed_family.get("MinVersion"), seed_family.get("MaxVersionTested")) != (
        TARGET_DEVICE_FAMILY, MIN_VERSION, MAX_TESTED_VERSION
    ):
        raise ValueError("Unexpected target device family in seed")
    seed_capabilities = _one(seed, _q(FOUNDATION, "Capabilities"), "seed capabilities")
    if [item.get("Name") for item in seed_capabilities] != ["runFullTrust"]:
        raise ValueError("Unexpected capabilities in seed")
    if seed_properties.findtext(_q(FOUNDATION, "PublisherDisplayName")) != PUBLISHER_DISPLAY_NAME:
        raise ValueError("Unexpected publisher display name in seed")

    # Validate the small set of logo paths that the new manifest will retain.
    logo = _asset_ref(seed_properties.findtext(_q(FOUNDATION, "Logo")), "package logo")
    visual_values = {name: seed_visual.get(name) for name in VISUAL_ATTRIBUTES}
    tile_values = {name: seed_tile.get(name) for name in TILE_ATTRIBUTES}
    for name in VISUAL_ATTRIBUTES:
        if not visual_values[name]:
            raise ValueError(f"Missing seed visual attribute: {name}")
        if name.endswith("Logo"):
            _asset_ref(visual_values[name], name)
    for name, value in tile_values.items():
        _asset_ref(value, name)

    ET.register_namespace("", FOUNDATION)
    ET.register_namespace("uap", UAP)
    ET.register_namespace("rescap", RESCAP)
    root = ET.Element(_q(FOUNDATION, "Package"), {"IgnorableNamespaces": "uap rescap"})
    ET.SubElement(root, _q(FOUNDATION, "Identity"), {
        "Name": NAME,
        "Publisher": PUBLISHER,
        "Version": version,
        "ProcessorArchitecture": "x64",
    })
    properties = ET.SubElement(root, _q(FOUNDATION, "Properties"))
    ET.SubElement(properties, _q(FOUNDATION, "DisplayName")).text = DISPLAY_NAME
    ET.SubElement(properties, _q(FOUNDATION, "PublisherDisplayName")).text = PUBLISHER_DISPLAY_NAME
    ET.SubElement(properties, _q(FOUNDATION, "Description")).text = DESCRIPTION
    ET.SubElement(properties, _q(FOUNDATION, "Logo")).text = logo.replace("/", "\\")

    resources = ET.SubElement(root, _q(FOUNDATION, "Resources"))
    ET.SubElement(resources, _q(FOUNDATION, "Resource"), {"Language": "en-us"})
    dependencies = ET.SubElement(root, _q(FOUNDATION, "Dependencies"))
    ET.SubElement(dependencies, _q(FOUNDATION, "TargetDeviceFamily"), {
        "Name": TARGET_DEVICE_FAMILY,
        "MinVersion": MIN_VERSION,
        "MaxVersionTested": MAX_TESTED_VERSION,
    })

    applications = ET.SubElement(root, _q(FOUNDATION, "Applications"))
    app = ET.SubElement(applications, _q(FOUNDATION, "Application"), {
        "Id": APP_ID,
        "Executable": EXE,
        "EntryPoint": ENTRY_POINT,
    })
    visual = ET.SubElement(app, _q(UAP, "VisualElements"), {
        name: value for name, value in visual_values.items() if value is not None
    })
    ET.SubElement(visual, _q(UAP, "DefaultTile"), {
        name: value for name, value in tile_values.items() if value is not None
    })
    capabilities = ET.SubElement(root, _q(FOUNDATION, "Capabilities"))
    ET.SubElement(capabilities, _q(RESCAP, "Capability"), {"Name": "runFullTrust"})

    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    inspect_manifest(data, version)
    return data


def resolve_package_version(
    local_test_version: str | None = None,
    latest_tag: str | None = None,
    head_commit: str | None = None,
    tag_commit: str | None = None,
) -> tuple[str, str]:
    app_version, _ = source_versions()
    validate_versions()
    app_parts = parse_semantic_version(app_version)
    if local_test_version:
        next_app = f"{app_parts[0]}.{app_parts[1]}.{app_parts[2] + 1}"
        expected = next_app + ".0"
        validate_msix_version(next_app, local_test_version)
        if local_test_version != expected:
            raise ValueError(f"Local test version must be the next patch candidate: {expected}")
        return local_test_version, "local-test-only"

    if latest_tag is None:
        latest_tag = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    latest_version = parse_semantic_version(latest_tag.removeprefix("v").removeprefix("V"))
    if app_parts < latest_version:
        raise ValueError("Source version is older than the latest release tag")
    if app_parts == latest_version:
        if head_commit is None:
            head_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT,
                check=True, capture_output=True, text=True,
            ).stdout.strip()
        if tag_commit is None:
            tag_commit = subprocess.run(
                ["git", "rev-list", "-n", "1", latest_tag], cwd=ROOT,
                check=True, capture_output=True, text=True,
            ).stdout.strip()
        if head_commit != tag_commit:
            raise ValueError(
                "Source contains changes after the latest public tag without a version bump. "
                "Refusing to reuse its Store version."
            )
    version = app_version + ".0"
    validate_versions(tag="v" + app_version, msix_version=version)
    return version, "store-release"


def prepare_local_test_build_root(destination: Path, app_version: str) -> Path:
    """Stage only application build inputs with a temporary, consistent version."""
    parse_semantic_version(app_version)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "app.py", destination / "app.py")
    shutil.copy2(ROOT / "BK-LMS-Downloader-icon-blue.ico", destination / "BK-LMS-Downloader-icon-blue.ico")
    (destination / "src").mkdir()
    shutil.copytree(ROOT / "src" / "bklms_downloader", destination / "src" / "bklms_downloader")
    (destination / "tools").mkdir()
    for relative in ("tools/build_desktop.py", "tools/prepare_ai_course.py"):
        shutil.copy2(ROOT / relative, destination / relative)

    project_file = destination / "pyproject.toml"
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_text, project_count = re.subn(
        r"(?m)^(version\s*=\s*)[\"'][^\"']+[\"']",
        lambda match: match.group(1) + f'"{app_version}"',
        project_text,
        count=1,
    )
    init_file = destination / "src" / "bklms_downloader" / "__init__.py"
    init_text = init_file.read_text(encoding="utf-8")
    init_text, init_count = re.subn(
        r"(?m)^(__version__\s*=\s*)[\"'][^\"']+[\"']",
        lambda match: match.group(1) + f'"{app_version}"',
        init_text,
        count=1,
    )
    if project_count != 1 or init_count != 1:
        raise ValueError("Could not stage a consistent local test version")
    project_file.write_text(project_text, encoding="utf-8")
    init_file.write_text(init_text, encoding="utf-8")
    return destination


def validate_package(package: Path, version: str, executable: Path) -> dict:
    with zipfile.ZipFile(package) as archive:
        names = [safe_name(item.filename) for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate entries")
        permitted = {"AppxManifest.xml", "AppxBlockMap.xml", "[Content_Types].xml", EXE}
        for name in names:
            if name not in permitted and not (name.startswith("Assets/") and Path(name).suffix.lower() in {".png", ".ico"}):
                raise ValueError(f"Unexpected runtime payload: {name}")
        for name in permitted:
            if name not in names:
                raise ValueError(f"Missing package member: {name}")
        root = inspect_manifest(archive.read("AppxManifest.xml"), version)
        missing_assets = _manifest_asset_references(root).difference(names)
        if missing_assets:
            raise ValueError(f"Missing branding assets: {sorted(missing_assets)}")
        payload = archive.read(EXE)
        if hashlib.sha256(payload).digest() != hashlib.sha256(executable.read_bytes()).digest():
            raise ValueError("Packaged EXE differs from tested fresh build")
        offset = struct.unpack_from("<I", payload, 0x3c)[0]
        if payload[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", payload, offset + 4)[0] != 0x8664:
            raise ValueError("EXE is not x64 PE")
        if struct.unpack_from("<H", payload, offset + 24 + 68)[0] != 2:
            raise ValueError("EXE must use Windows GUI subsystem")
        if archive.testzip() is not None:
            raise ValueError("Corrupt archive")
        identity = root.find(_q(FOUNDATION, "Identity"))
    return {
        "filename": package.name,
        "bytes": package.stat().st_size,
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "identity": dict(identity.attrib),
        "application_id": APP_ID,
        "entry_point": ENTRY_POINT,
        "files": len(names),
        "launch_policy": "manifest-registered AUMID; no physical shortcut or alias",
        "signing": "unsigned; signing is not verified by structural validation",
    }


def build(seed: Path, makeappx: Path, destination: Path, local_test_version: str | None = None) -> Path:
    version, build_mode = resolve_package_version(local_test_version)
    # Detect inaccessible SDK binaries before spending time on a desktop build.
    subprocess.run([str(makeappx), "/?"], stdout=subprocess.DEVNULL, check=False)
    destination.mkdir(parents=True, exist_ok=True)
    package = destination / f"BK-LMS-Downloader_{version}_x64.msix"
    if package.exists():
        raise FileExistsError("Choose an empty output directory; packages are never overwritten")
    with zipfile.ZipFile(seed) as archive:
        manifest_data = create_store_manifest(archive.read("AppxManifest.xml"), version)
        root = inspect_manifest(manifest_data, version)
        assets = {}
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = safe_name(item.filename)
            if name.startswith("Assets/") and Path(name).suffix.lower() in {".png", ".ico"}:
                assets[name] = archive.read(item)
        missing_assets = _manifest_asset_references(root).difference(assets)
        if missing_assets:
            raise ValueError(f"Identity seed is missing visual assets: {sorted(missing_assets)}")

    with tempfile.TemporaryDirectory(prefix="bklms_msix_build_") as build_temporary:
        if build_mode == "local-test-only":
            app_version = ".".join(version.split(".")[:3])
            build_root = prepare_local_test_build_root(Path(build_temporary) / "source", app_version)
        else:
            build_root = ROOT
        started = time.time()
        build_script = build_root / "tools" / "build_desktop.py"
        build_env = os.environ.copy()
        if build_mode == "local-test-only":
            source_path = str(build_root / "src")
            build_env["PYTHONPATH"] = os.pathsep.join(
                [source_path, build_env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
        subprocess.run([sys.executable, str(build_script)], cwd=build_root, env=build_env, check=True)
        executable = build_root / "dist" / EXE
        if not executable.is_file() or not executable.stat().st_size or executable.stat().st_mtime <= started:
            raise RuntimeError("Fresh Windows executable not produced")
        for test in SELF_TESTS:
            subprocess.run([str(executable), "--self-test-" + test], cwd=build_root, check=True, timeout=180)
        with tempfile.TemporaryDirectory(prefix="bklms_msix_payload_") as payload_temporary:
            payload = Path(payload_temporary) / "payload"
            payload.mkdir()
            (payload / "AppxManifest.xml").write_bytes(manifest_data)
            for name, data in assets.items():
                target = payload / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            shutil.copy2(executable, payload / EXE)
            subprocess.run([str(makeappx), "pack", "/d", str(payload), "/p", str(package)], check=True)
            subprocess.run([str(makeappx), "unpack", "/p", str(package), "/d", str(Path(payload_temporary) / "verified")], check=True)
        report = validate_package(package, version, executable)
        report["build_mode"] = build_mode
        report["signing"] = (
            "unsigned local test package; never submit"
            if build_mode == "local-test-only"
            else "unsigned Store package; requires official submission signing"
        )
        report["exe_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        report["exe_bytes"] = executable.stat().st_size
        report["exe_mtime"] = executable.stat().st_mtime
        print(json.dumps(report, indent=2))
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-package", required=True, type=Path, help="Trusted previous Store MSIX; identity and branding only")
    parser.add_argument("--makeappx", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/store")
    parser.add_argument(
        "--local-test-version",
        help="Build an unsigned next-patch candidate for local validation only; never a Store submission",
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Build on Windows using the build virtual environment")
    build(args.identity_package.resolve(), args.makeappx.resolve(), args.output.resolve(), args.local_test_version)
