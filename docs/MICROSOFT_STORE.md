# Microsoft Store versioning

The application uses semantic `MAJOR.MINOR.PATCH` versions. Microsoft Store
MSIX identity versions must use four numeric components and this project's
revision component must always remain `0`.

Current public release:

```text
Application / Git tag: 1.2.0 / v1.2.0
Microsoft Store MSIX:  1.2.0.0
```

Next release candidate:

```text
Application / future Git tag: 1.3.0 / v1.3.0
Microsoft Store MSIX:       1.3.0.0
```

Do not reuse the packaging-only `1.1.1.0` version and do not create versions
such as `1.3.0.1`. Before preparing the next MSIX, run:

```powershell
python tools/validate_versions.py --tag v1.3.0 --msix-version 1.3.0.0
```

The command fails if `pyproject.toml`, package `__version__`, the tag, or the
MSIX version disagree, or if the fourth MSIX component is non-zero.
