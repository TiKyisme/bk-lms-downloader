# Microsoft Store launch troubleshooting

If an older desktop or taskbar shortcut says Windows cannot find the app under
`C:\Program Files\WindowsApps\...`, the shortcut may still point to a package
folder from before a Store update.

1. Open **Start**, search for **BK-LMS Downloader**, and launch that entry.
2. If Start launches the app, delete the old BK-LMS Downloader desktop shortcut
   and pin the app again from its Start entry.
3. Do not browse into or launch files directly from `WindowsApps`; Windows
   manages package locations and may replace versioned package folders during
   updates.
4. If the Start entry is also missing or does not launch, check for an update in
   Microsoft Store. Reinstall from Store only if the registered Start entry
   remains broken.

The package-registered Start entry is the supported launch route. This workaround
does not require deleting app data or manually changing package files.
