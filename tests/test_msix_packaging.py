import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_msix import FOUNDATION, inspect_manifest, safe_name


def manifest(**changes):
    values = dict(Name='TiKyisme.BK-LMSDownloader', Publisher='CN=synthetic-test',
                  Version='1.5.1.0', ProcessorArchitecture='x64')
    values.update(changes)
    attrs = ' '.join(f'{k}="{v}"' for k, v in values.items())
    return (f'<Package xmlns="{FOUNDATION}"><Identity {attrs}/><Applications>'
            '<Application Executable="BK-LMS-Downloader.exe" EntryPoint="Windows.FullTrustApplication"/>'
            '</Applications><Capabilities><Capability Name="runFullTrust"/></Capabilities></Package>').encode()


@pytest.mark.parametrize('path', ['../secret', '/secret', 'C:/secret', 'Assets/../../secret'])
def test_reject_unsafe_payload_paths(path):
    with pytest.raises(ValueError):
        safe_name(path)


@pytest.mark.parametrize('changes', [{'Name': 'wrong'}, {'Publisher': ''}, {'ProcessorArchitecture': 'arm64'}, {'Version': '1.5.0.0'}])
def test_reject_wrong_package_identity(changes):
    with pytest.raises(ValueError):
        inspect_manifest(manifest(**changes), '1.5.1.0')


def test_accept_reserved_desktop_manifest():
    assert inspect_manifest(manifest(), '1.5.1.0') is not None
