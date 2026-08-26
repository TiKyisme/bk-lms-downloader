# Changelog

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
