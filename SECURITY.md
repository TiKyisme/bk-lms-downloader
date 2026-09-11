# Security policy

## Supported versions

Security fixes are considered for the latest public release on `main`. Older
versions may receive guidance, but users should update before reporting a
reproducible issue.

## What to report

Examples include unintended exposure of BK-LMS authentication data, unsafe
filesystem writes or deletion, release/update-distribution compromise, leakage
of local course material, or AI Study Pack privacy failures. Treat cookies,
Authorization headers, session values, and private course material as sensitive.

## Report privately

If the repository's **Report a vulnerability** option is available, use it.
Otherwise contact the maintainer privately through the contact method listed on
the GitHub profile. Do not open a public issue for a suspected vulnerability.

Never include passwords, cookies, session tokens, Authorization headers, full
LMS exports, private course files, personally identifying information, or local
filesystem paths in a public report. A minimal redacted reproduction and the
affected release version are usually enough to begin triage.

## What to expect

Reports are reviewed in good faith. The maintainer may ask for a redacted
reproduction, acknowledge the issue, and coordinate a fix or disclosure when
appropriate. No fixed response-time or remediation-time guarantee is made.

## Security boundaries

BK-LMS Downloader does not collect BK-LMS passwords. Authentication occurs in
the user-controlled Chrome session; cookies are used only in memory for the
active sync. AI Study Pack preparation is local and does not call external AI
services. These boundaries are documented further in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
