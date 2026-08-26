# BK-LMS Downloader v1.0.0 release checklist

Complete this manual checklist before creating the public tag.

- [ ] `pytest -q` is green locally.
- [ ] GitHub Actions test workflow is green.
- [ ] Windows EXE is built as `dist/BK-LMS-Downloader.exe`.
- [ ] EXE opens without Python installed.
- [ ] Chrome opens and official BK-LMS login works.
- [ ] **Nhập từ BK-LMS** lists accessible courses.
- [ ] Manual Add Course works and remembers the output folder.
- [ ] Sync selected works.
- [ ] Sync all works sequentially.
- [ ] A second sync skips unchanged files.
- [ ] Vietnamese filenames are correct.
- [ ] Compact output folders are correct.
- [ ] Linked courses are flattened.
- [ ] Videos are skipped.
- [ ] Removing a saved course does not remove its files.
- [ ] Update notice is checked with a newer/no-newer release scenario.
- [ ] Optional AI preparation is checked from a source install with `.[ai]`.
- [ ] No credentials, cookies, or session material are present in repository files or logs.
- [ ] README screenshot and download instructions are current.
- [ ] Create `v1.0.0` only after all above smoke tests pass.
