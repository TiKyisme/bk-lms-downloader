# Changelog

## 0.1.0 - 2026-08-26

Initial public alpha.

- Refactored the working deep crawler into a reusable Python package.
- Added Windows GUI with browser-based BK-LMS login.
- Video downloads are disabled by default.
- Added Standard and Complete Archive modes.
- Preserved deep crawling of Moodle Page/Folder/Book/URL and linked courses.
- Added CLI for advanced/batch use.
- Added sync behavior: existing files are skipped unless changed/forced.
- Added optional `prepare_ai_course.py` tool under `tools/`.
- Added tests, build scripts, GitHub Actions CI and Windows release workflow.
