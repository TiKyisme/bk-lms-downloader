# Chrome startup diagnostics

Clicking login starts one worker. The badge reports Chrome opened as soon as
the controlled window exists. Navigation uses Selenium's eager strategy
(DOMContentLoaded); it no longer waits for every image/asset or sleeps another
0.8 seconds. Import and sync still explicitly wait for document readiness.
Browser-dependent actions remain disabled until that worker finishes, preventing
two threads from navigating the same driver. Navigation failure retains the
browser so the user can retry. Healthy drivers are reused and closed ones replaced.

The normal per-user app log records only named durations and exception types:
worker_start, options, driver_resolution, driver_create, browser_ready,
navigation, ready_wait, total, ui_browser_ready. Durations use perf_counter.
No cookies, URLs, credentials or raw driver stderr are copied into these records.
The badge does not claim successful authentication merely because navigation
completed.

For a reproducible measurement, run:

```text
python app.py --diagnose-chrome
BK-LMS-Downloader-Windows.exe --diagnose-chrome
```

This explicit diagnostic opens a fresh controlled Chrome, navigates to the
public LMS page, prints event timings where a console is available, and closes
that browser. Detailed phase timings are in the per-user app log. Run twice to
compare first/cached startup; do not delete a user's Selenium cache. Never run
this command as an automatic network/GUI test in CI.

Selenium Manager still selects a compatible driver using its normal version-aware
cache. First-time driver downloads may be slower. No fixed ChromeDriver, offline
override, PATH shortcuts, new driver-manager dependency or prewarming is added.
Manager statistics reporting is disabled. Chrome and Manager discovery paths are
not written to the timing log.

Onefile extraction happens before the app window is displayed, so it is separate
from click-to-browser measurements. Antivirus impact and a genuinely fresh
Windows profile require measurement on a clean machine; do not disable security
software. macOS uses the same Selenium-managed startup.
