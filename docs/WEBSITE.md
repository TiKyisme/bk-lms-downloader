# Product website

The static Vietnamese product website lives in `website/` and is deployed by
the GitHub Pages workflow from that directory. It has no build step, analytics,
tracking, cookies, backend, or third-party advertising scripts.

Expected public URL:

```text
https://tikyisme.github.io/bk-lms-downloader/
```

## Demo asset

If a reviewed public demo recording is available, place it at:

```text
website/assets/bk-lms-demo.mp4
```

Use H.264 MP4 with readable UI text. The site loads video metadata only and
falls back to `website/assets/app-window.png` if the video is unavailable.
Review the recording for private data before committing it; do not publish
passwords, cookies, session data, student identifiers, private messages, or
course material not intended for public release.

## One-time GitHub setting

After the workflow is merged, enable GitHub Pages for this repository and set
the source to **GitHub Actions**. No application runtime setting is involved.
