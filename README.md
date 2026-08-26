# BK-LMS Downloader

Unofficial utility for downloading and organizing course materials from **BK-LMS (HCMUT)**.

> **Status:** v0.2.0 alpha. The crawler works on real BK-LMS course data, but Moodle courses can be structured differently. Please report edge cases.

## What changed in v0.2.0

The downloader now uses a **compact output layout** instead of mirroring every Moodle folder level.

- Removed **Complete Archive** mode.
- Linked learning-material courses are still crawled, but their files are moved into the root course folders instead of creating `COURSE_.../nested/...` trees.
- Sections such as `Lab 1` ... `Lab 8` are grouped into one `03_Lab` folder.
- Assignment sections are grouped into `04_Bài tập`.
- Lecture/chapter/week/slide sections are grouped into `02_Bài giảng`.
- Textbooks and references are grouped into `05_Tài liệu tham khảo`.
- Useful Moodle Page/inline text and images are saved directly in the same compact folder instead of `_inline_content/assets/...`.
- Technical JSON metadata is moved into a single `_meta` folder.
- Video files are always skipped.

## Output example

Instead of a deep tree like:

```text
Course/
└── 00_Chung/
    └── 01_Linked course/
        └── COURSE_.../
            ├── 05_Lab 1/
            │   └── nested/
            └── 12_Lab 8/
```

v0.2.0 produces:

```text
Course/
├── 01_Thông tin môn học/
├── 02_Bài giảng/
├── 03_Lab/
│   ├── Lab 1_ Introduction - guide.pdf
│   ├── Lab 1_ Introduction - topology.pkt
│   ├── ...
│   └── Lab 8_ Wireless Network - worksheet.pdf
├── 04_Bài tập/
├── 05_Tài liệu tham khảo/
├── 06_Khác/
└── _meta/
    ├── course_structure.json
    ├── download_manifest.json
    └── stats.json
```

The LMS can still be crawled deeply; **only the saved output is flattened**. Filenames are prefixed with their source section/activity where useful so files from different labs or chapters do not become ambiguous.

## Easiest way to use it on Windows

For public releases, download `BK-LMS-Downloader.exe` from the repository **Releases** page and double-click it.

GUI flow:

1. Click **Mở Chrome để đăng nhập**.
2. Log in to BK-LMS in the Chrome window.
3. Paste a course URL such as `https://lms.hcmut.edu.vn/course/view.php?id=123456`.
4. Choose an output folder.
5. Click **TẢI / SYNC TÀI LIỆU**.
6. Click **Mở thư mục kết quả** when finished.

The application never asks you to type your BK-LMS password into the app. Authentication happens directly on the official BK-LMS website in Chrome.

## What it downloads

- PDF, PPT/PPTX, Word/Excel files, ZIPs and other study resources.
- Moodle Page / Folder / Book / URL / Lesson content.
- Images and downloadable assets embedded in useful course/page content.
- Files inside a linked learning-material course.

Interactive activities such as Forum, Quiz and Assignment submissions are not crawled as downloadable document trees.

### Video

Video download is intentionally **not supported**. MP4/MKV/WebM/MOV/AVI/M4V files are always skipped so the app does not unexpectedly download many GB.

A linked course named “Video” can still be traversed: PDFs, slides, lab files and other non-video resources inside it are downloaded normally.

## Vietnamese filenames

v0.1.1+ repairs common Moodle/HTTP filename mojibake such as:

```text
CHÆ¯Æ NG 1_Giá»›i THIá»†U
```

into proper Unicode Vietnamese names.

To repair files downloaded by an older release without re-downloading them:

```powershell
python tools/repair_existing_filenames.py "D:\University\BK_LMS_Data\Tên môn"
```

Preview first, then apply:

```powershell
python tools/repair_existing_filenames.py "D:\University\BK_LMS_Data\Tên môn" --apply
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

Start GUI:

```powershell
bklms-gui
```

or:

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

Multiple courses:

```powershell
Copy-Item courses.example.txt courses.txt
# Edit courses.txt, one course URL per line.
bklms --courses-file courses.txt --output "D:\University\HK1"
```

Do not follow linked learning-material courses:

```powershell
bklms `
  --course-url "https://lms.hcmut.edu.vn/course/view.php?id=123456" `
  --no-follow-linked-courses
```

## Build the Windows EXE

```powershell
.\scripts\build_windows.ps1
```

Output:

```text
dist\BK-LMS-Downloader.exe
```

Tags matching `v*` trigger the Windows GitHub Actions release workflow.

## Optional: prepare course files for AI study

The repository also contains a separate experimental tool:

```text
tools/prepare_ai_course.py
```

It converts downloaded material into Markdown/retrieval-friendly content for AI study workflows. It is intentionally separate from the downloader.

Install optional dependencies:

```powershell
pip install -r requirements-ai.txt
```

## Privacy and security

- The app does not collect or store your BK-LMS username/password.
- Login happens directly on the official BK-LMS site in Chrome.
- Session cookies are used in memory during the current run.
- Do not share private course content or authentication/session material.

See [SECURITY.md](SECURITY.md).

## Disclaimer

This is an **unofficial** student utility. It is not affiliated with, sponsored by, or endorsed by HCMUT or BK-LMS.

Use it only with courses and materials that your account is legitimately authorized to access. Respect course policies, copyright, and the rights of instructors/content owners. The project is not intended to bypass access controls.

## Development roadmap

- [x] Refactor prototype into a package
- [x] Single-course Windows GUI
- [x] Deep Moodle crawling
- [x] Permanent video skipping
- [x] Vietnamese filename repair
- [x] Compact output layout
- [x] Group Lab / Assignment / Lecture sections
- [x] Flatten linked-course output into root course folders
- [x] Tests + GitHub Actions
- [ ] Test against more BK-LMS course/module layouts
- [ ] My Courses / Sync All GUI
- [ ] Better per-file progress and retry UI
- [ ] Auto-update support

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License. See [LICENSE](LICENSE).
