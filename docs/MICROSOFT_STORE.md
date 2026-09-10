# Microsoft Store versioning

The application uses semantic `MAJOR.MINOR.PATCH` versions. Microsoft Store
MSIX identity versions must use four numeric components and this project's
revision component must always remain `0`.

For the next application release:

```text
Application / Git tag: 1.1.4 / v1.1.4
Microsoft Store MSIX:  1.1.4.0
```

Do not reuse the packaging-only `1.1.1.0` version and do not create versions
such as `1.1.4.1`. Before preparing an MSIX, run:

```powershell
python tools/validate_versions.py --tag v1.1.4 --msix-version 1.1.4.0
```

The command fails if `pyproject.toml`, package `__version__`, the tag, or the
MSIX version disagree, or if the fourth MSIX component is non-zero.
