# Microsoft Store versioning

The application uses semantic `MAJOR.MINOR.PATCH` versions. Microsoft Store
MSIX identity versions must use four numeric components and this project's
revision component must always remain `0`.

Current public GitHub release:

```text
Application / Git tag: 1.5.1 / v1.5.1
```

Microsoft Store status:

The v1.5.1 Store update has not yet been submitted. Microsoft Store may still
display the previously approved version.

Next Microsoft Store submission target:

```text
Microsoft Store MSIX:       1.5.1.0
```

Do not reuse the packaging-only `1.1.1.0` version and do not create versions
such as `1.3.0.1`. Before preparing the next MSIX, run:

```powershell
python tools/validate_versions.py --tag v1.5.1 --msix-version 1.5.1.0
```

The command fails if `pyproject.toml`, package `__version__`, the tag, or the
MSIX version disagree, or if the fourth MSIX component is non-zero.

## Reproducible x64 MSIX packaging

Use the build virtual environment after installing `.[dev]`. Run on Windows:

```powershell
.venv-build/Scripts/python.exe tools/build_msix.py --identity-package <trusted-previous.msix> --makeappx <path-to-makeappx.exe> --output dist/store
```

The existing local Store packages were created with MSIX Packaging Tool. The
builder reuses their manifest and branded `Assets` only, preserving Store
identity, desktop entry point, Windows minimum version and `runFullTrust`
capability. Obtain the seed from a trusted previous submission and verify its
Name, Publisher and PublisherDisplayName against Partner Center's Product
identity page. Never substitute guessed identity values. The seed remains local.

The command derives the version from the canonical app version with a fourth
component of zero, rebuilds the Windows EXE with PyInstaller's clean mode, runs
all four packaged self-tests, and packs/unpacks with MakeAppx validation enabled.
It checks the exact payload allowlist, asset references, x64 GUI executable,
fresh EXE hash and manifest identity. Existing output packages are not replaced.
MakeAppx is available in Windows SDK or MSIX Packaging Tool's SDK directory.

The output is an **unsigned Store submission package**. Microsoft signs Store
submissions; local sideload testing needs a separately test-signed copy and a
trusted test certificate. Never upload that test copy or commit certificates,
keys, generated MSIX files, or package workspaces. WACK and an installed-package
launch test are separate checks; the builder does not claim those were run.

## Partner Center submission checklist

1. Open BK-LMS Downloader (`9N1TTL7WPJT0`) in Partner Center and compare Product
   identity with the package manifest (Name `TiKyisme.BK-LMSDownloader`).
2. Check that `1.5.1.0` exceeds every currently approved or submitted package
   version; local historical packages alone do not establish live Store state.
3. Create an update submission. On Packages, upload only the validated
   `BK-LMS-Downloader_1.5.1.0_x64.msix` and wait for package validation.
4. Preserve existing listing, privacy policy and age ratings unless a required
   field is incomplete. Review any capability/certification requirements.
5. Suggested update notes: "Fixes synchronization and AI Study Pack progress
   reporting. Progress now reflects active work accurately and no longer
   reaches 100% before the full batch has completed."
6. Review the summary and submit. Record the submission ID and actual state;
   submission does not mean certification or publication has completed.

References: [MSIX signing](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide)
and [uploading MSIX packages](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/upload-app-packages).
