#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

requested_arch="${1:-$(uname -m)}"
case "$requested_arch" in
  arm64|aarch64) asset_arch="arm64" ;;
  x86_64|x64) asset_arch="x64" ;;
  *) echo "Unsupported macOS architecture: $requested_arch" >&2; exit 2 ;;
esac

case "$(uname -m)" in
  arm64|aarch64) host_arch="arm64" ;;
  x86_64|x64) host_arch="x64" ;;
  *) echo "Unsupported macOS host architecture: $(uname -m)" >&2; exit 2 ;;
esac
if [[ "$asset_arch" != "$host_arch" ]]; then
  echo "PyInstaller must build macOS artifacts natively (host: $host_arch, requested: $asset_arch)." >&2
  exit 2
fi

venv="$repo_root/.venv-build-macos"
python_bin="$venv/bin/python"
app_name="BK-LMS Downloader"
app_bundle="$repo_root/dist/$app_name.app"
dmg_path="$repo_root/dist/BK-LMS-Downloader-macOS-$asset_arch.dmg"

if [[ ! -x "$python_bin" ]]; then
  python3 -m venv "$venv"
fi

"$python_bin" -m pip install --upgrade pip
"$python_bin" -m pip install ".[dev]"
if [[ "${BKLMS_SKIP_TESTS:-0}" != "1" ]]; then
  "$python_bin" -m pytest
fi

icon_source="$repo_root/BK-LMS-Downloader-icon-blue.png"
iconset="$repo_root/build/BK-LMS-Downloader.iconset"
macos_icon="$repo_root/build/BK-LMS-Downloader.icns"
rm -rf "$iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$icon_source" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double_size=$((size * 2))
  sips -z "$double_size" "$double_size" "$icon_source" \
    --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$macos_icon"

"$python_bin" tools/build_desktop.py

if [[ ! -d "$app_bundle" ]]; then
  echo "Build finished but app bundle was not found: $app_bundle" >&2
  exit 1
fi

packaged_executable="$app_bundle/Contents/MacOS/$app_name"
for self_test in --self-test-ai --self-test-sync; do
  "$packaged_executable" "$self_test"
done

# Optional signing is deliberately opt-in.  Configure a real Developer ID
# identity in CI later; unsigned builds stay usable for development testing.
if [[ -n "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp \
    --sign "$MACOS_CODESIGN_IDENTITY" "$app_bundle"
fi

stage_dir="$repo_root/build/macos-dmg-$asset_arch"
rm -rf "$stage_dir"
mkdir -p "$stage_dir"
ditto "$app_bundle" "$stage_dir/$app_name.app"
ln -s /Applications "$stage_dir/Applications"
rm -f "$dmg_path"
hdiutil create \
  -volname "BK-LMS Downloader" \
  -srcfolder "$stage_dir" \
  -ov \
  -format UDZO \
  "$dmg_path"

# Supply a keychain profile only in a protected release environment after
# importing a real Developer ID Application certificate.  Development builds
# intentionally skip this branch and remain unsigned.
if [[ -n "${MACOS_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
  if [[ -z "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
    echo "Notarization requires MACOS_CODESIGN_IDENTITY with a real Developer ID Application certificate." >&2
    exit 2
  fi
  xcrun notarytool submit "$dmg_path" \
    --keychain-profile "$MACOS_NOTARY_KEYCHAIN_PROFILE" \
    --wait
  xcrun stapler staple "$dmg_path"
fi

echo "Build OK: $dmg_path"
