# Contributing

Thanks for helping improve BK-LMS Downloader.

## Development setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
pytest
```

Run the GUI:

```powershell
bklms-gui
```

Run the CLI:

```powershell
bklms --help
```

## Pull requests

- Start with the [pull request template](.github/PULL_REQUEST_TEMPLATE.md) and
  keep each change focused.
- Keep authentication browser-based; never add password collection.
- Do not commit course materials, cookies, session files, or personal data.
- Preserve non-destructive course removal and local-only AI Study Pack preparation.
- Add/update tests for parser/crawler behavior where possible.
- Do not add video downloading to the main downloader; video files are intentionally skipped to keep downloads lightweight.
- Explain Moodle module edge cases in the PR description.

## Testing against BK-LMS

Automated tests use local HTML fixtures only. If you manually test against a
real course, only use courses your own account is authorized to access.
Never attach downloaded course materials or LMS exports to an issue or pull
request; use synthetic fixtures instead.
