# Changelog

## 1.0.5 - 2026-08-27

- Make the release gate wait for the windowed packaged AI self-test process and
  preserve diagnostic tracebacks when that gate fails.

## 1.0.4 - 2026-08-27

- Clean BK-LMS accessibility prefixes from imported course names while
  preserving course codes and class metadata.
- Simplify Delete and AI preparation actions to checked courses or all courses.
- Bundle the complete local AI preparation runtime in the Windows release and
  validate HTML, PDF, and PPTX extraction with a packaged `--self-test-ai` gate.

## 1.0.3 - 2026-08-27

- Bundle local AI preparation for the Windows release instead of relying on a
  source-only subprocess.
- Add sequential AI preparation for checked courses or all saved courses, with
  per-course progress and isolated failures.

## 1.0.2 - 2026-08-27

- Remove BK-LMS accessibility text "Khóa học được đánh dấu sao" from imported
  course names without changing course codes or other metadata.

## 1.0.1 - 2026-08-27

- Add one-course, checked-course, and all-course removal from the My Courses
  list with explicit Vietnamese confirmation dialogs.
- Keep downloaded files and folders untouched: course removal only updates the
  application's persisted `courses.json` list.

## 1.0.0 - 2026-08-26

- Stabilize the student-focused BK-LMS Downloader public release.
- Include Chrome login, My Courses import from the authenticated `/my/courses.php`
  page, manual/imported courses, remembered output
  folders, compact Sync selected / Sync all, passive updates, and optional local
  AI preparation.
- Complete privacy, reliability, packaging, documentation, and release checks.

## 0.7.0 - 2026-08-26

- Add conservative retries for transient requests, safe same-name file handling,
  corrupt JSON backups, and redacted rotating application logs.
- Harden the Windows PyInstaller build to collect package submodules.
- Improve normal GUI error messages without exposing stack traces.

## 0.6.0 - 2026-08-26

- Add optional **Công cụ → Chuẩn bị cho AI** support for already downloaded
  courses, reusing the local course-preparation tool.
- Keep AI dependencies, cloud/API requirements, and video transcription out of
  the normal downloader installation and workflow.

## 0.5.0 - 2026-08-26

- Add **Nhập từ BK-LMS** course discovery with defensive Moodle My Courses parsing.
- Let students explicitly choose detected courses before saving them, while
  retaining manual URL entry as a fallback.

## 0.4.0 - 2026-08-26

- Add a non-blocking GitHub Release update notice for newer stable versions.
- Open the official release page only after the user explicitly clicks the notice.

## 0.3.1 - 2026-08-26

- Remember the last selected output directory when adding or editing courses.
- Simplify the My Courses window around login, course selection, sync, and a
  compact result/log area.
- Remove the output-path column and large metric dashboard from the main list;
  show the selected course's folder as a small detail line instead.
- Keep existing v0.3.0 sync and download behavior unchanged.

## 0.3.0 - 2026-08-26

- Add the **My Courses** dashboard with persistent local course configuration.
- Add course selection plus sequential **Sync selected** and **Sync all** actions
  that reuse one authenticated in-memory session per batch.
- Add per-course last-sync metadata, result statuses, course-code detection, and
  a concise sync summary/activity log.
- Keep Tkinter responsive by running Chrome/session and download work off the UI
  thread and forwarding structured events through the existing queue pattern.
- Add safe handling for damaged course configuration and duplicate course URLs.
- Add CourseStore, SyncManager, course-code, and batch-failure regression tests.
- Keep the compact output layout and permanently skip video files.

## 0.2.0 - 2026-08-26

- Remove Complete Archive mode from GUI, CLI, and crawler.
- Replace deep Moodle-shaped output trees with a compact student-facing layout.
- Group sections into a small set of folders: course info, lectures, labs, assignments, references, and other.
- Merge `Lab 1` ... `Lab 8` files into one `03_Lab` folder while preserving section context in filenames.
- Flatten files from linked learning-material courses into the root course folders instead of creating `COURSE_...` trees.
- Save useful Moodle Page/inline text and downloadable assets directly in the category folder instead of `_inline_content/assets/...` nesting.
- Move technical JSON files into a single `_meta` folder.
- Keep deep crawling internally and keep video downloads permanently disabled.
- Add regression tests for compact section grouping and linked-course flattening.

## 0.1.1 - 2026-08-26

- Fix Vietnamese filenames corrupted by legacy HTTP `Content-Disposition` encoding.
- Normalize downloaded filenames to Unicode NFC before saving on Windows.
- Remove the video-download option from both GUI and CLI.
- Video responses and common video extensions are always skipped, while linked material courses are still crawled for PDFs/slides/documents.
- Add `tools/repair_existing_filenames.py` so old downloads can be renamed without downloading them again.
- Add regression tests for Vietnamese filename decoding and permanent video skipping.

## 0.1.0 - 2026-08-26

Initial public alpha.

- Refactored the working deep crawler into a reusable Python package.
- Added Windows GUI with browser-based BK-LMS login.
- Added deep crawling of Moodle Page/Folder/Book/URL and linked courses.
- Added CLI for advanced/batch use.
- Added sync behavior: existing files are skipped unless changed/forced.
- Added optional `prepare_ai_course.py` tool under `tools/`.
- Added tests, build scripts, GitHub Actions CI and Windows release workflow.
