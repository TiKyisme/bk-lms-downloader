# BK-LMS Downloader

Unofficial utility for downloading and organizing course materials from
**BK-LMS (HCMUT)**.

The goal is simple: a student should be able to open the app, log in to BK-LMS
in Chrome, paste a course link, choose a folder, and sync the course materials
without manually clicking every PDF/PPTX/resource.

> **Status:** v0.1.0 alpha. The crawler is working on real BK-LMS course data,
> but Moodle courses can be structured differently. Please report edge cases.

## What it does

- Opens Chrome so you sign in directly on the official BK-LMS website.
- Downloads resources and keeps the LMS section/activity order.
- Crawls deeper into Moodle Page / Folder / Book / URL / Lesson content.
- Can follow a linked learning-material course.
- Saves inline course/page text and assets for offline use.
- Skips existing files on later runs, so it can be used as a lightweight sync.
- **Video download is OFF by default** to avoid unexpectedly downloading many GB.
- Advanced users can use the CLI for one or many courses.

## Easiest way to use it on Windows

For public releases, download:

```text
BK-LMS-Downloader.exe
```

from the repository's **Releases** page and double-click it.

The GUI flow is:

1. Click **Mở Chrome để đăng nhập**.
2. Log in to BK-LMS in the Chrome window.
3. Paste a course URL such as:
   `https://lms.hcmut.edu.vn/course/view.php?id=123456`
4. Choose an output folder.
5. Click **TẢI / SYNC TÀI LIỆU**.
6. When finished, click **Mở thư mục kết quả**.

The application never asks you to type your BK-LMS password into the app.
Authentication is performed on the official website in Chrome.

## Download modes

### Standard mode — recommended

Default mode. It downloads learning files, saves useful Moodle page text/assets,
and follows useful internal links without preserving every web artifact.

### Complete archive

Enable **Complete archive** in the GUI (or `--archive` in CLI) to also keep HTML
snapshots and external-link shortcuts. This is useful for archival/research but
creates a noisier folder tree.

### Video

Video is disabled by default. Enable **Tải video** only when you actually need
course videos.

## Output example

```text
BK_LMS_Data/
└── Mạng máy tính (CO3093)_.../
    ├── 00_Chung/
    ├── 01_Thông tin môn học/
    ├── 02_Textbook/
    ├── 03_Cisco CCIE Professional Dev - Routing TCP_IP/
    ├── 04_Reference design/
    ├── 05_Chapter 1 - Introduction - Network edge Network Core/
    ├── ...
    ├── _course_structure.json
    ├── _download_manifest.json
    └── _stats.json
```

## Run from source

Requirements:

- Windows 10/11 recommended
- Python 3.10+
- Google Chrome

Setup:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

Start the GUI:

```powershell
bklms-gui
```

Or:

```powershell
python app.py
```

## CLI

One course:

```powershell
bklms `
  --course-url "https://lms.hcmut.edu.vn/course/view.php?id=123456" `
  --output "D:\University\BK_LMS_Data"
```

Download videos too:

```powershell
bklms `
  --course-url "https://lms.hcmut.edu.vn/course/view.php?id=123456" `
  --output "D:\University\BK_LMS_Data" `
  --download-video
```

Complete archive:

```powershell
bklms `
  --course-url "https://lms.hcmut.edu.vn/course/view.php?id=123456" `
  --output "D:\University\BK_LMS_Data" `
  --archive
```

Multiple courses:

```powershell
Copy-Item courses.example.txt courses.txt
# Edit courses.txt, one course URL per line.
bklms --courses-file courses.txt --output "D:\University\HK1"
```

## Build the Windows EXE

From PowerShell:

```powershell
.\scripts\build_windows.ps1
```

The executable is generated at:

```text
dist\BK-LMS-Downloader.exe
```

Git tags matching `v*` trigger the GitHub Actions release workflow, which builds
the Windows EXE and attaches it to the GitHub Release automatically.

## Optional: prepare course files for AI study

The repository also contains an experimental, separate tool:

```text
tools/prepare_ai_course.py
```

It converts downloaded course material into Markdown/retrieval-friendly content.
It is intentionally separate from the downloader so normal users do not need AI,
Whisper, CUDA, or document-processing dependencies.

Install optional dependencies:

```powershell
pip install -r requirements-ai.txt
```

Video transcription is optional and not enabled unless explicitly requested by
that tool.

## Project structure

```text
src/bklms_downloader/
├── auth.py       # Chrome login -> authenticated requests session
├── parser.py     # Moodle course/page parsing
├── crawler.py    # deep crawler + downloader/sync engine
├── gui.py        # student-friendly Windows GUI
├── cli.py        # advanced/batch CLI
├── utils.py
├── models.py
└── config.py

tools/
└── prepare_ai_course.py

tests/
.github/workflows/
scripts/
```

## Privacy and security

- The app does not collect or store your BK-LMS username/password.
- Login happens directly on the official BK-LMS site in Chrome.
- Session cookies are used in memory during the current run.
- Do not share downloaded private course content or authentication/session files.

See [SECURITY.md](SECURITY.md).

## Disclaimer

This is an **unofficial** student utility. It is not affiliated with, sponsored
by, or endorsed by HCMUT or BK-LMS.

Use it only with courses and materials that your own account is legitimately
authorized to access. Respect course policies, copyright, and the rights of
instructors and content owners. The project is not intended to bypass access
controls or permissions.

## Development roadmap

- [x] Refactor prototype into a package
- [x] GUI for single-course download/sync
- [x] Video opt-in
- [x] Standard / Complete Archive modes
- [x] CLI batch mode
- [x] Tests + GitHub Actions
- [x] Automated Windows EXE release workflow
- [ ] Test against more BK-LMS course/module layouts
- [ ] My Courses / Sync All GUI
- [ ] Better per-file progress and retry UI
- [ ] Auto-update support
- [ ] Optional AI preparation integration after downloader stabilizes

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License. See [LICENSE](LICENSE).
