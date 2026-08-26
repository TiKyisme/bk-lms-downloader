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

- Keep authentication browser-based; never add password collection.
- Do not commit course materials, cookies, session files, or personal data.
- Add/update tests for parser/crawler behavior where possible.
- Keep video opt-in by default because course videos can be very large.
- Explain Moodle module edge cases in the PR description.

## Testing against BK-LMS

Automated tests use local HTML fixtures only. If you manually test against a
real course, only use courses your own account is authorized to access.
