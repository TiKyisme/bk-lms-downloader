# Microsoft Store versioning

The application uses semantic `MAJOR.MINOR.PATCH` versions. Microsoft Store
MSIX identity versions must use four numeric components and this project's
revision component must always remain `0`.

Current public GitHub release:

```text
Application / Git tag: 1.5.1 / v1.5.1
```

Microsoft Store status:

Do not build or submit MSIX `1.5.1.0` from current main: application-code
changes have landed after the public v1.5.1 release. Microsoft Store may still
display the previously approved version.

Next combined release target, after the Store-launch fix is validated and
release preparation bumps the application source version:

```text
Application / Git tag: 1.5.2 / v1.5.2
Microsoft Store MSIX:  1.5.2.0
```

The fourth MSIX version component must remain `0`. Do not reuse the packaging-
only `1.1.1.0` version or create versions such as `1.5.2.1`. During future
release preparation, after the source version is `1.5.2`, run:

```powershell
python tools/validate_versions.py --tag v1.5.2 --msix-version 1.5.2.0
```

The command fails if `pyproject.toml`, package `__version__`, the tag, or the
MSIX version disagree, or if the fourth MSIX component is non-zero.

## Reproducible x64 MSIX packaging

Use the build virtual environment after installing `.[dev]`. Run on Windows for
a local, test-only candidate while source version is still `1.5.1`:

```powershell
.venv-build/Scripts/python.exe tools/build_msix.py --identity-package <trusted-previous.msix> --makeappx <path-to-makeappx.exe> --output <empty-temp-directory> --local-test-version 1.5.2.0
```

The builder reads a seed's identity and branding assets, then generates a new
reviewed manifest. It does not carry forward historical extensions or shortcut
declarations. Obtain the seed from a trusted previous Store submission and
verify its Name, Publisher and PublisherDisplayName against Partner Center's
Product identity page. An unsigned file can be a legitimate Store submission
artifact, but its provenance must be independently known; an unverified local
build is not evidence of a prior submission. Never substitute guessed identity
values. Keep the seed local.

The local-test option accepts only the next patch candidate, does not change the
canonical source version, and never builds the already-public version. For a
Store release, first bump source version and create the matching release tag;
then omit `--local-test-version`. The builder rebuilds the Windows EXE, runs all
four packaged self-tests, and packs/unpacks with MakeAppx. It checks the payload
allowlist, manifest launch policy, asset references, x64 GUI executable and
fresh EXE hash. Existing output packages are not replaced.

The output is unsigned. For local install/update testing, sign only a disposable
copy with a test certificate matching the package Publisher, trust it locally,
and remove the package and certificate after testing. Never upload a test copy
or commit certificates, keys, generated MSIX files, or package workspaces.
WACK and installed-package launch/update tests are separate checks; the builder
does not claim those were run.

## Partner Center submission checklist

1. Open BK-LMS Downloader (`9N1TTL7WPJT0`) in Partner Center and compare Product
   identity with the package manifest (Name `TiKyisme.BK-LMSDownloader`).
2. Check that `1.5.2.0` exceeds every currently approved or submitted package
   version; local historical packages alone do not establish live Store state.
3. Create an update submission. On Packages, upload only the validated
   `BK-LMS-Downloader_1.5.2.0_x64.msix` and wait for package validation.
4. Preserve existing listing, privacy policy and age ratings unless a required
   field is incomplete. Review any capability/certification requirements.
5. Suggested update notes: "Fixes synchronization and AI Study Pack progress
   reporting. Progress now reflects active work accurately and no longer
   reaches 100% before the full batch has completed."
6. Review the summary and submit. Record the submission ID and actual state;
   submission does not mean certification or publication has completed.

References: [MSIX signing](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide)
and [uploading MSIX packages](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/upload-app-packages).
