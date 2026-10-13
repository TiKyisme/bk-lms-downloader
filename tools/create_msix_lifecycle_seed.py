"""Create temporary, synthetic identity/branding input for MSIX lifecycle tests.

This is test scaffolding only. The generated ZIP is not a distributable package
and must never be checked in or submitted to the Microsoft Store.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
NAME = "TiKyisme.BK-LMSDownloader"
PUBLISHER = "CN=73CAA01F-F63A-4EAE-BDD2-53B50789E666"
APP_ID = "BKLMSDOWNLOADER"
EXE = "BK-LMS-Downloader.exe"

PNG_ASSETS = {
    "Assets/StoreLogo.png": (50, 50),
    "Assets/Square150x150Logo.png": (150, 150),
    "Assets/Square44x44Logo.png": (44, 44),
    "Assets/Wide310x150Logo.png": (310, 150),
    "Assets/Square310x310Logo.png": (310, 310),
    "Assets/Square71x71Logo.png": (71, 71),
}


def create_seed(destination: Path) -> None:
    source_image = Image.open(ROOT / "BK-LMS-Downloader-icon-blue.png").convert("RGBA")
    generated_assets: dict[str, bytes] = {}
    for asset_path, size in PNG_ASSETS.items():
        image = ImageOps.fit(source_image, size, method=Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        generated_assets[asset_path] = buffer.getvalue()
    generated_assets["Assets/BK-LMS-Downloader-icon-blue.ico"] = (
        ROOT / "BK-LMS-Downloader-icon-blue.ico"
    ).read_bytes()

    ET.register_namespace("", FOUNDATION)
    ET.register_namespace("uap", UAP)
    ET.register_namespace("rescap", RESCAP)
    package = ET.Element(f"{{{FOUNDATION}}}Package", {"IgnorableNamespaces": "uap rescap"})
    ET.SubElement(package, f"{{{FOUNDATION}}}Identity", {
        "Name": NAME,
        "Publisher": PUBLISHER,
        "Version": "1.3.0.0",
        "ProcessorArchitecture": "x64",
    })
    properties = ET.SubElement(package, f"{{{FOUNDATION}}}Properties")
    ET.SubElement(properties, f"{{{FOUNDATION}}}DisplayName").text = "BK-LMS Downloader"
    ET.SubElement(properties, f"{{{FOUNDATION}}}PublisherDisplayName").text = "TiKyisme"
    ET.SubElement(properties, f"{{{FOUNDATION}}}Description").text = "Synthetic lifecycle test seed"
    ET.SubElement(properties, f"{{{FOUNDATION}}}Logo").text = "Assets\\StoreLogo.png"

    resources = ET.SubElement(package, f"{{{FOUNDATION}}}Resources")
    ET.SubElement(resources, f"{{{FOUNDATION}}}Resource", {"Language": "en-us"})
    dependencies = ET.SubElement(package, f"{{{FOUNDATION}}}Dependencies")
    ET.SubElement(dependencies, f"{{{FOUNDATION}}}TargetDeviceFamily", {
        "Name": "Windows.Desktop",
        "MinVersion": "10.0.17763.0",
        "MaxVersionTested": "10.0.22000.1",
    })
    applications = ET.SubElement(package, f"{{{FOUNDATION}}}Applications")
    app = ET.SubElement(applications, f"{{{FOUNDATION}}}Application", {
        "Id": APP_ID,
        "Executable": EXE,
        "EntryPoint": "Windows.FullTrustApplication",
    })
    visual = ET.SubElement(app, f"{{{UAP}}}VisualElements", {
        "DisplayName": "BK-LMS Downloader",
        "Description": "Synthetic lifecycle test seed",
        "BackgroundColor": "#1F2937",
        "Square150x150Logo": "Assets\\Square150x150Logo.png",
        "Square44x44Logo": "Assets\\Square44x44Logo.png",
    })
    ET.SubElement(visual, f"{{{UAP}}}DefaultTile", {
        "Wide310x150Logo": "Assets\\Wide310x150Logo.png",
        "Square310x310Logo": "Assets\\Square310x310Logo.png",
        "Square71x71Logo": "Assets\\Square71x71Logo.png",
    })
    capabilities = ET.SubElement(package, f"{{{FOUNDATION}}}Capabilities")
    ET.SubElement(capabilities, f"{{{RESCAP}}}Capability", {"Name": "runFullTrust"})
    manifest = ET.tostring(package, encoding="utf-8", xml_declaration=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AppxManifest.xml", manifest)
        for name, data in generated_assets.items():
            archive.writestr(name, data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    create_seed(args.output.resolve())
    print(f"Synthetic identity seed created: {args.output.resolve()}")


if __name__ == "__main__":
    main()
