"""Build an unsigned Store MSIX using a trusted previous package as identity seed.

Only the manifest and branded Assets are reused; the executable is always rebuilt.
Run with the build virtual environment's Python on Windows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from validate_versions import source_versions, validate_versions

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'
NAME = 'TiKyisme.BK-LMSDownloader'
EXE = 'BK-LMS-Downloader.exe'
SELF_TESTS = ('ai', 'lite-runtime', 'sync', 'scroll')


def safe_name(name: str) -> str:
    name = name.replace('\\', '/')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name:
        raise ValueError('Unsafe package path')
    return name


def inspect_manifest(data: bytes, version: str | None = None) -> ET.Element:
    root = ET.fromstring(data)
    identity = root.find(f'{{{FOUNDATION}}}Identity')
    if identity is None or identity.get('Name') != NAME or not identity.get('Publisher', '').startswith('CN='):
        raise ValueError('Trusted Store identity is required')
    if identity.get('ProcessorArchitecture') != 'x64':
        raise ValueError('Only the existing x64 package is supported')
    if version and identity.get('Version') != version:
        raise ValueError('MSIX version mismatch')
    apps = root.findall(f'{{{FOUNDATION}}}Applications/{{{FOUNDATION}}}Application')
    if len(apps) != 1 or apps[0].get('Executable') != EXE or apps[0].get('EntryPoint') != 'Windows.FullTrustApplication':
        raise ValueError('Unexpected desktop entry point')
    capabilities = root.find(f'{{{FOUNDATION}}}Capabilities')
    if capabilities is None or [item.get('Name') for item in capabilities] != ['runFullTrust']:
        raise ValueError('Unexpected capabilities; review before packaging')
    return root


def validate_package(package: Path, version: str, executable: Path) -> dict:
    with zipfile.ZipFile(package) as archive:
        names = [safe_name(item.filename) for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate entries')
        permitted = {'AppxManifest.xml', 'AppxBlockMap.xml', '[Content_Types].xml', EXE}
        for name in names:
            if name not in permitted and not (name.startswith('Assets/') and Path(name).suffix.lower() in {'.png', '.ico'}):
                raise ValueError(f'Unexpected runtime payload: {name}')
        for name in permitted:
            if name not in names:
                raise ValueError(f'Missing package member: {name}')
        root = inspect_manifest(archive.read('AppxManifest.xml'), version)
        for element in root.iter():
            refs = [value for key, value in element.attrib.items() if key.endswith('Logo') or key == 'Icon']
            if element.tag == f'{{{FOUNDATION}}}Logo':
                refs.append(element.text or '')
            for ref in refs:
                ref = safe_name(ref.replace('[{Package}]\\', ''))
                if ref not in names:
                    raise ValueError(f'Missing branding asset: {ref}')
        payload = archive.read(EXE)
        if hashlib.sha256(payload).digest() != hashlib.sha256(executable.read_bytes()).digest():
            raise ValueError('Packaged EXE differs from tested fresh build')
        offset = struct.unpack_from('<I', payload, 0x3c)[0]
        if payload[offset:offset + 4] != b'PE\0\0' or struct.unpack_from('<H', payload, offset + 4)[0] != 0x8664:
            raise ValueError('EXE is not x64 PE')
        if struct.unpack_from('<H', payload, offset + 24 + 68)[0] != 2:
            raise ValueError('EXE must use Windows GUI subsystem')
        if archive.testzip() is not None:
            raise ValueError('Corrupt archive')
        identity = root.find(f'{{{FOUNDATION}}}Identity')
    return {'filename': package.name, 'bytes': package.stat().st_size,
            'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
            'identity': dict(identity.attrib), 'entry_point': EXE, 'files': len(names),
            'signing': 'unsigned Store submission; not a sideload package'}


def build(seed: Path, makeappx: Path, destination: Path) -> Path:
    # Detect inaccessible SDK binaries before spending time on a desktop build.
    subprocess.run([str(makeappx), '/?'], stdout=subprocess.DEVNULL, check=False)
    app_version, _ = source_versions()
    version = app_version + '.0'
    validate_versions(tag='v' + app_version, msix_version=version)
    destination.mkdir(parents=True, exist_ok=True)
    package = destination / f'BK-LMS-Downloader_{version}_x64.msix'
    if package.exists():
        raise FileExistsError('Choose an empty output directory; packages are never overwritten')
    with zipfile.ZipFile(seed) as archive:
        manifest = archive.read('AppxManifest.xml')
        root = inspect_manifest(manifest)
        identity = root.find(f'{{{FOUNDATION}}}Identity')
        if tuple(map(int, identity.get('Version', '').split('.'))) >= tuple(map(int, version.split('.'))):
            raise ValueError('Target must be newer than trusted seed package')
        # Preserve all namespace prefixes/extension semantics from the proven manifest.
        import io
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(manifest), events=('start-ns',)):
            ET.register_namespace(prefix, uri)
        identity.set('Version', version)
        assets = {safe_name(i.filename): archive.read(i) for i in archive.infolist()
                  if not i.is_dir() and safe_name(i.filename).startswith('Assets/')
                  and Path(i.filename).suffix.lower() in {'.png', '.ico'}}
    started = time.time()
    subprocess.run([sys.executable, str(ROOT / 'tools/build_desktop.py')], cwd=ROOT, check=True)
    executable = ROOT / 'dist' / EXE
    if not executable.is_file() or not executable.stat().st_size or executable.stat().st_mtime <= started:
        raise RuntimeError('Fresh Windows executable not produced')
    for test in SELF_TESTS:
        subprocess.run([str(executable), '--self-test-' + test], cwd=ROOT, check=True, timeout=180)
    with tempfile.TemporaryDirectory(prefix='bklms_msix_') as temporary:
        payload = Path(temporary) / 'payload'
        payload.mkdir()
        ET.ElementTree(root).write(payload / 'AppxManifest.xml', encoding='utf-8', xml_declaration=True)
        for name, data in assets.items():
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        shutil.copy2(executable, payload / EXE)
        subprocess.run([str(makeappx), 'pack', '/d', str(payload), '/p', str(package)], check=True)
        subprocess.run([str(makeappx), 'unpack', '/p', str(package), '/d', str(Path(temporary) / 'verified')], check=True)
    report = validate_package(package, version, executable)
    report['exe_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
    report['exe_bytes'] = executable.stat().st_size
    report['exe_mtime'] = executable.stat().st_mtime
    print(json.dumps(report, indent=2))
    return package


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity-package', required=True, type=Path, help='Trusted previous Store MSIX; identity and branding only')
    parser.add_argument('--makeappx', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/store')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Build on Windows using the build virtual environment')
    build(args.identity_package.resolve(), args.makeappx.resolve(), args.output.resolve())
