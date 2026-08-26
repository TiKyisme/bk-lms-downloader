# Security

## Authentication

BK-LMS Downloader does **not** ask for or store your BK-LMS username/password.
Authentication happens directly in the Chrome window opened by Selenium. The
app copies the authenticated browser cookies into an in-memory HTTP session for
the current run.

Do not upload or commit cookies, session dumps, downloaded private course data,
or other authentication material to GitHub.

## Reporting a vulnerability

Please open a GitHub issue without including credentials, cookies, private LMS
content, or personal information. For a sensitive report, contact the repository
maintainer privately through the contact method listed on the GitHub profile.
