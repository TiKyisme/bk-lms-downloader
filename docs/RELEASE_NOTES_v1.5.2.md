# BK-LMS Downloader v1.5.2 — Release Candidate

These notes describe the candidate for manual testing. v1.5.2 has not yet been
tagged or published.

## Synchronization

- Recoverable resource failures are reported as partial results instead of
  making an otherwise completed course look fatally failed.
- Completion remains below 100% until the sync batch truly finishes.

## AI Study Packs

- Empty or unusable packs are rejected with an actionable warning instead of
  being reported as successful output.
- Course folders are resolved more safely, and semantically empty legacy packs
  are rebuilt.
- DOCX, XLSX, XLSM, and CSV lecturer sources are supported.
- A Coursewave no-match remains optional and does not block a local pack when
  usable LMS material exists.

## Course selection

- Course checkboxes start unchecked after app launch or restart.
- Selected-only actions operate only on courses the student explicitly checks;
  separate all-course actions remain available.

## Windows launch

- New packages no longer declare the historical version-bound desktop
  shortcut. Start/AUMID package launch registration remains in place.
- The historical stale-shortcut failure was not directly reproduced during
  candidate validation; this note does not claim that it was.

## Apple Silicon

- The arm64 build is intended for Apple Silicon Macs, including M1 through M5
  and newer. Physical M5 hardware was not separately tested.
