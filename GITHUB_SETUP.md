# GitHub release setup

The canonical repository is `TiKyisme/bk-lms-downloader`. Before creating a
future release tag, update both source version declarations, the changelog, and
the release checklist, then run:

```powershell
python tools/validate_versions.py --tag vX.Y.Z
python -m pytest
python -m compileall -q src tools app.py
```

Only after the reviewed commit is on `main` and CI is green should a maintainer
create and push an annotated tag:

```powershell
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The `release-windows.yml` workflow first validates source/tag consistency,
compilation, and the full test suite. Native Windows, macOS arm64, and macOS
x64 jobs then build explicit platform assets. One final job creates a single
GitHub Release containing:

- `BK-LMS-Downloader-Windows.exe`
- `BK-LMS-Downloader-macOS-arm64.dmg`
- `BK-LMS-Downloader-macOS-x64.dmg`

Before public launch:

1. Confirm the single release job contains all three named platform assets.
2. Test the Windows EXE on a clean Windows machine.
3. Test both macOS architectures on matching native Macs.
4. Test at least several BK-LMS courses with different Moodle activity types.
