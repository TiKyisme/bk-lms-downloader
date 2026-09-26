# Microsoft Store versioning

The application uses semantic `MAJOR.MINOR.PATCH` versions. Microsoft Store
MSIX identity versions must use four numeric components and this project's
revision component must always remain `0`.

Current public GitHub release:

```text
Application / Git tag: 1.5.0 / v1.5.0
```

Microsoft Store status:

The v1.5.0 Store update has not yet been submitted. Microsoft Store may still
display the previously approved version.

Next Microsoft Store submission target:

```text
Microsoft Store MSIX:       1.5.0.0
```

Do not reuse the packaging-only `1.1.1.0` version and do not create versions
such as `1.3.0.1`. Before preparing the next MSIX, run:

```powershell
python tools/validate_versions.py --tag v1.5.0 --msix-version 1.5.0.0
```

The command fails if `pyproject.toml`, package `__version__`, the tag, or the
MSIX version disagree, or if the fourth MSIX component is non-zero.
