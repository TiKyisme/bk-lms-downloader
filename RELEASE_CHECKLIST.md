# BK-LMS Downloader v1.0.6 release checklist

Complete this manual checklist before creating the public tag.

- [ ] `pytest -q` is green locally.
- [ ] GitHub Actions test workflow is green.
- [ ] Windows EXE is built as `dist/BK-LMS-Downloader.exe`.
- [ ] EXE opens without Python installed.
- [ ] Chrome opens and official BK-LMS login works.
- [ ] **Nhập từ BK-LMS** lists accessible courses.
- [ ] Imported names do not include `Khóa học được đánh dấu sao` or `Tên khóa học` prefixes.
- [ ] Manual Add Course works and remembers the output folder.
- [ ] Sync selected works.
- [ ] Sync all works sequentially.
- [ ] A second sync skips unchanged files.
- [ ] Vietnamese filenames are correct.
- [ ] Compact output folders are correct.
- [ ] Linked courses are flattened.
- [ ] Videos are skipped.
- [ ] Removing checked courses does not remove their files or folders.
- [ ] Removing all saved courses does not remove any downloaded files or folders.
- [ ] Update notice is checked with a newer/no-newer release scenario.
- [ ] Prepare multiple checked courses for AI from the packaged EXE.
- [ ] Prepare all courses for AI from the packaged EXE.
- [ ] Each course gets its own `AI_Knowledge` folder.
- [ ] A failure in one course does not stop the remaining AI batch.
- [ ] Original downloaded files remain untouched by AI preparation.
- [ ] Packaged EXE requires no Python or pip installation for AI preparation.
- [ ] Packaged `BK-LMS-Downloader.exe --self-test-ai` exits successfully.
- [ ] Packaged `BK-LMS-Downloader.exe --diagnose-ai` reports all AI imports and synthetic batch success.
- [ ] No credentials, cookies, or session material are present in repository files or logs.
- [ ] README screenshot and download instructions are current.
- [ ] Create `v1.0.6` only after all above smoke tests pass.
