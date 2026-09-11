# GitHub repository setup

The canonical repository is `TiKyisme/bk-lms-downloader`.

## Release automation

The release workflow validates the tagged source, builds Windows plus native
macOS arm64/x64 assets, runs packaged checks, generates `SHA256SUMS.txt`, and
creates one GitHub Release. Follow [docs/RELEASING.md](docs/RELEASING.md) for
the canonical human release process and use `RELEASE_CHECKLIST.md` for the
version-specific acceptance checklist.

## Recommended repository settings

- Set the repository description and topics listed in the README/release notes.
- Protect `main` with required test checks, up-to-date branches, blocked force
  pushes, and blocked deletion. A solo maintainer need not require a second
  approval by default.
- Enable GitHub Private Vulnerability Reporting when available.
- Enable Dependabot version and security updates.

These remote settings are intentionally not changed by repository automation.
