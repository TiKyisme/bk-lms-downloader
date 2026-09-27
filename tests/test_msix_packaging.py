import struct
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_msix import (  # noqa: E402
    APP_ID,
    DESCRIPTION,
    DISPLAY_NAME,
    ENTRY_POINT,
    EXE,
    FOUNDATION,
    MIN_VERSION,
    NAME,
    PUBLISHER,
    PUBLISHER_DISPLAY_NAME,
    RESCAP,
    TARGET_DEVICE_FAMILY,
    UAP,
    _manifest_asset_references,
    create_store_manifest,
    inspect_manifest,
    prepare_local_test_build_root,
    resolve_package_version,
    safe_name,
    validate_package,
)

APP_VERSION = "1.5.2.0"


def seed_manifest(**changes):
    attributes = {
        "Name": NAME,
        "Publisher": PUBLISHER,
        "Version": "1.3.0.0",
        "ProcessorArchitecture": "x64",
    }
    attributes.update(changes)
    identity = " ".join(f'{key}="{value}"' for key, value in attributes.items())
    return f'''<Package xmlns="{FOUNDATION}"
        xmlns:uap="{UAP}"
        xmlns:rescap="{RESCAP}"
        xmlns:desktop7="http://schemas.microsoft.com/appx/manifest/desktop/windows10/7"
        xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
        xmlns:mp="http://schemas.microsoft.com/appx/2014/phone/manifest"
        IgnorableNamespaces="uap uap10 desktop7 rescap">
      <Identity {identity}/>
      <Properties>
        <DisplayName>{DISPLAY_NAME}</DisplayName>
        <PublisherDisplayName>{PUBLISHER_DISPLAY_NAME}</PublisherDisplayName>
        <Description>{DESCRIPTION}</Description>
        <Logo>Assets\\StoreLogo.png</Logo>
        <uap10:PackageIntegrity><uap10:Content Enforcement="on"/></uap10:PackageIntegrity>
      </Properties>
      <Resources><Resource Language="en-us"/></Resources>
      <Dependencies><TargetDeviceFamily Name="{TARGET_DEVICE_FAMILY}" MinVersion="{MIN_VERSION}" MaxVersionTested="10.0.22000.1"/></Dependencies>
      <Applications>
        <Application Id="{APP_ID}" Executable="{EXE}" EntryPoint="{ENTRY_POINT}">
          <uap:VisualElements BackgroundColor="transparent" DisplayName="BK-LMS Downloader"
             Square150x150Logo="Assets\\BKLMSDOWNLOADER-Square150x150Logo.png"
             Square44x44Logo="Assets\\BKLMSDOWNLOADER-Square44x44Logo.png" Description="{DESCRIPTION}">
            <uap:DefaultTile Wide310x150Logo="Assets\\BKLMSDOWNLOADER-Wide310x150Logo.png"
              Square310x310Logo="Assets\\BKLMSDOWNLOADER-Square310x310Logo.png"
              Square71x71Logo="Assets\\BKLMSDOWNLOADER-Square71x71Logo.png"/>
          </uap:VisualElements>
          <Extensions><desktop7:Extension Category="windows.shortcut">
            <desktop7:Shortcut File="[{{Common Programs}}]\\BK-LMS Downloader.lnk"
              Icon="[{{Package}}]\\Assets\\BK-LMS-Downloader-icon-blue.ico"/>
          </desktop7:Extension></Extensions>
        </Application>
      </Applications>
      <Capabilities><rescap:Capability Name="runFullTrust"/></Capabilities>
      <mp:PhoneIdentity PhoneProductId="seed-only" PhonePublisherId="seed-only"/>
    </Package>'''.encode()


def candidate_manifest():
    return create_store_manifest(seed_manifest(), APP_VERSION)


def test_safe_package_paths_reject_traversal_and_absolute_paths():
    for path in ("../secret", "/secret", "C:/secret", "Assets/../../secret"):
        with pytest.raises(ValueError):
            safe_name(path)


def test_legacy_seed_is_rebuilt_without_historical_extensions():
    root = inspect_manifest(candidate_manifest(), APP_VERSION)
    tags = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}

    assert "Extensions" not in tags
    assert "Extension" not in tags
    assert "Shortcut" not in tags
    assert "AppExecutionAlias" not in tags
    assert "PhoneIdentity" not in tags
    assert "PackageIntegrity" not in tags


def test_reviewed_manifest_preserves_store_identity_and_launch_contract():
    root = inspect_manifest(candidate_manifest(), APP_VERSION)
    identity = root.find(f"{{{FOUNDATION}}}Identity")
    application = root.find(f"{{{FOUNDATION}}}Applications/{{{FOUNDATION}}}Application")
    family = root.find(f"{{{FOUNDATION}}}Dependencies/{{{FOUNDATION}}}TargetDeviceFamily")
    capabilities = root.find(f"{{{FOUNDATION}}}Capabilities")

    assert identity.attrib == {
        "Name": NAME,
        "Publisher": PUBLISHER,
        "Version": APP_VERSION,
        "ProcessorArchitecture": "x64",
    }
    assert application is not None
    assert (application.get("Id"), application.get("Executable"), application.get("EntryPoint")) == (
        APP_ID, EXE, ENTRY_POINT
    )
    assert family is not None and family.get("Name") == TARGET_DEVICE_FAMILY
    assert family.get("MinVersion") == MIN_VERSION
    assert capabilities is not None
    assert [capability.get("Name") for capability in capabilities] == ["runFullTrust"]
    assert _manifest_asset_references(root) == {
        "Assets/StoreLogo.png",
        "Assets/BKLMSDOWNLOADER-Square150x150Logo.png",
        "Assets/BKLMSDOWNLOADER-Square44x44Logo.png",
        "Assets/BKLMSDOWNLOADER-Wide310x150Logo.png",
        "Assets/BKLMSDOWNLOADER-Square310x310Logo.png",
        "Assets/BKLMSDOWNLOADER-Square71x71Logo.png",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"Name": "wrong"},
        {"Publisher": "CN=other"},
        {"ProcessorArchitecture": "arm64"},
        {"Version": "1.5.1.0"},
    ],
)
def test_reject_wrong_package_identity(changes):
    root = ET.fromstring(candidate_manifest())
    identity = root.find(f"{{{FOUNDATION}}}Identity")
    for key, value in changes.items():
        identity.set(key, value)
    with pytest.raises(ValueError):
        inspect_manifest(ET.tostring(root), APP_VERSION)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        r"C:\Program Files\WindowsApps\TiKyisme.BK-LMSDownloader_1.3.0.0_x64__publisher\BK-LMS-Downloader.exe",
        r"[{Package}]\TiKyisme.BK-LMSDownloader_1.3.0.0_x64__publisher\BK-LMS-Downloader.exe",
    ],
)
def test_reject_windowsapps_and_version_bound_executable_paths(unsafe_path):
    root = ET.fromstring(candidate_manifest())
    app = root.find(f"{{{FOUNDATION}}}Applications/{{{FOUNDATION}}}Application")
    app.set("Executable", unsafe_path)
    with pytest.raises(ValueError):
        inspect_manifest(ET.tostring(root), APP_VERSION)


def test_reject_any_unreviewed_manifest_extension():
    root = ET.fromstring(candidate_manifest())
    app = root.find(f"{{{FOUNDATION}}}Applications/{{{FOUNDATION}}}Application")
    extensions = ET.SubElement(app, f"{{{FOUNDATION}}}Extensions")
    ET.SubElement(
        extensions,
        "{http://schemas.microsoft.com/appx/manifest/desktop/windows10/7}Extension",
        {"Category": "windows.shortcut"},
    )
    with pytest.raises(ValueError, match="extension"):
        inspect_manifest(ET.tostring(root), APP_VERSION)


def test_local_test_build_uses_next_patch_without_reusing_public_version():
    assert resolve_package_version("1.5.2.0") == ("1.5.2.0", "local-test-only")
    with pytest.raises(ValueError):
        resolve_package_version("1.5.1.0")
    with pytest.raises(ValueError):
        resolve_package_version("1.5.3.0")
    with pytest.raises(ValueError, match="without a version bump"):
        resolve_package_version(latest_tag="v1.5.1", head_commit="main", tag_commit="release")
    assert resolve_package_version(
        latest_tag="v1.5.1", head_commit="release", tag_commit="release"
    ) == ("1.5.1.0", "store-release")


def test_local_test_build_stages_temporary_app_version_without_touching_source(tmp_path: Path):
    test_root = prepare_local_test_build_root(tmp_path / "candidate-source", "1.5.2")

    staged_version = (test_root / "src/bklms_downloader/__init__.py").read_text(encoding="utf-8")
    staged_project = (test_root / "pyproject.toml").read_text(encoding="utf-8")
    canonical_init = (Path(__file__).resolve().parents[1] / "src/bklms_downloader/__init__.py").read_text(encoding="utf-8")

    assert '__version__ = "1.5.2"' in staged_version
    assert 'version = "1.5.2"' in staged_project
    assert '__version__ = "1.5.1"' in canonical_init


def synthetic_pe() -> bytes:
    payload = bytearray(0x200)
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x84, 0x8664)
    struct.pack_into("<H", payload, 0x80 + 24 + 68, 2)
    return bytes(payload)


def write_test_package(path: Path, manifest_data: bytes, assets: set[str]):
    executable = synthetic_pe()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest_data)
        archive.writestr("AppxBlockMap.xml", b"test block map")
        archive.writestr("[Content_Types].xml", b"test content types")
        archive.writestr(EXE, executable)
        for name in assets:
            archive.writestr(name, b"synthetic image asset")
    return executable


def test_package_validation_requires_every_declared_visual_asset(tmp_path: Path):
    manifest_data = candidate_manifest()
    root = inspect_manifest(manifest_data, APP_VERSION)
    package = tmp_path / "candidate.msix"
    executable_path = tmp_path / EXE
    executable = write_test_package(
        package,
        manifest_data,
        _manifest_asset_references(root) - {"Assets/StoreLogo.png"},
    )
    executable_path.write_bytes(executable)

    with pytest.raises(ValueError, match="Missing branding assets"):
        validate_package(package, APP_VERSION, executable_path)


def test_package_validation_accepts_x64_manifest_assets_and_gui_executable(tmp_path: Path):
    manifest_data = candidate_manifest()
    root = inspect_manifest(manifest_data, APP_VERSION)
    package = tmp_path / "candidate.msix"
    executable_path = tmp_path / EXE
    executable = write_test_package(package, manifest_data, _manifest_asset_references(root))
    executable_path.write_bytes(executable)

    report = validate_package(package, APP_VERSION, executable_path)

    assert report["identity"]["ProcessorArchitecture"] == "x64"
    assert report["application_id"] == APP_ID
    assert report["entry_point"] == ENTRY_POINT
    assert report["launch_policy"] == "manifest-registered AUMID; no physical shortcut or alias"
