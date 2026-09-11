# Releasing

This is the canonical release process. `RELEASE_CHECKLIST.md` remains the
version-specific manual acceptance checklist.

1. Confirm the intended source version, tag, changelog entry, and MSIX version
   are consistent. The Store revision component must remain `0`.
2. Run:

   ```powershell
   python -m pytest
   python -m compileall -q src tools app.py
   python tools/validate_versions.py --tag vX.Y.Z --msix-version X.Y.Z.0
   ```

3. Review the version-specific checklist and commit the reviewed release state
   to `main`.
4. Push `main` and wait for the test workflow to pass.
5. Create and push an annotated, immutable tag only after CI is green:

   ```powershell
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. The release workflow validates the tag, builds Windows plus native macOS
   arm64/x64 artifacts, runs packaged checks, creates `SHA256SUMS.txt`, and
   publishes one GitHub Release with all assets.
7. Verify the release assets, checksums, and release notes. Submit the signed
   MSIX to Microsoft Store separately when applicable.

Do not rewrite published tags or release history. Native macOS validation must
run on matching macOS runners or hardware; Store submission and certification
are external release activities.

## Repository rules recommendation

Protect `main` with a GitHub ruleset or branch-protection rule that requires the
test workflow, requires branches to be up to date before merge, blocks force
pushes and branch deletion, and does not require a second human approval for a
solo maintainer by default.
