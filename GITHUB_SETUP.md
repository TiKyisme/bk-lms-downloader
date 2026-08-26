# Push this repo to GitHub

From the project directory:

```powershell
git init
git add .
git commit -m "Release v0.1.0"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bk-lms-downloader.git
git push -u origin main
```

Create the first release:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The `release-windows.yml` workflow will build `BK-LMS-Downloader.exe` on a
Windows GitHub runner and attach it to the GitHub Release.

Before public launch:

1. Replace `YOUR_USERNAME` links in README if you add repository-specific links.
2. Add a real screenshot/GIF under `docs/screenshots/`.
3. Test the `.exe` on a clean Windows machine.
4. Test at least several BK-LMS courses with different Moodle activity types.
