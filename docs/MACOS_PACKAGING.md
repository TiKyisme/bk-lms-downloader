# macOS packaging

`scripts/build_macos.sh` must run on the target Mac architecture; PyInstaller
does not cross-compile a macOS app from Windows or an Intel app from Apple
Silicon. It builds a clickable `BK-LMS Downloader.app`, runs the packaged AI and
sync self-tests, then creates a DMG containing the app plus an `Applications`
shortcut.

The application continues to use Selenium Manager through `webdriver.Chrome`,
so it does not hardcode a Windows Chrome path. On macOS, Selenium Manager can
use the standard Chrome bundle at
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` when Chrome is
installed normally.

Current release jobs use native GitHub-hosted runners:

- Apple Silicon: `macos-14` (arm64)
- Intel: `macos-15-intel` (x64)

## Signing and notarization

Development DMGs are intentionally unsigned. Gatekeeper can warn users or
require an explicit approval before first launch. Do not bypass this by adding
a fake certificate.

For a polished public release, import a real **Developer ID Application**
certificate into the macOS CI keychain and set `MACOS_CODESIGN_IDENTITY`. The
build script will then sign the app with Hardened Runtime and a timestamp. After
signing, set `MACOS_NOTARY_KEYCHAIN_PROFILE` for a real App Store Connect
notarytool keychain profile; the script submits the final DMG and staples the
returned ticket. These values should come from protected GitHub Secrets in a
future signing-enabled workflow, never from the repository.

## Manual Mac acceptance checklist

- Build on the intended native architecture and mount the produced DMG.
- Drag the app to Applications using the included shortcut.
- Launch the app, sign in with Chrome, import a course, and sync it.
- Confirm **Mở thư mục** opens Finder.
- Confirm settings, course list, and logs live under
  `~/Library/Application Support/BK-LMS-Downloader/`, not beside the app.
- Run the bundled app executable with `--self-test-ai` and `--self-test-sync`.
- On a signed/notarized release, run `codesign --verify --deep --strict` and
  `spctl --assess --type open` against the app/DMG.
