# Architecture

BK-LMS Downloader is a local desktop utility. It uses the official BK-LMS
website in a controlled Chrome window and stores downloaded material only in
user-selected local folders.

## Sync flow

```text
GUI
  -> controlled Chrome/Selenium login
  -> in-memory authenticated HTTP session
  -> course discovery
  -> SyncManager
  -> crawler/downloader
  -> atomic local course/settings metadata persistence
```

The GUI owns interaction and lifecycle state. Chrome credentials are entered on
BK-LMS, not into application fields. Browser cookies are used only for the
active local session; they are not persisted with course settings.

`SyncManager` coordinates selected courses, progress, cancellation, and
per-course results. The crawler writes downloads defensively so a failed
replacement does not discard an existing completed file. Removing courses from
the app list never deletes downloaded folders from disk.

## AI Study Pack flow

```text
Downloaded course
  -> local temporary preparation workspace
  -> source extraction and indexing
  -> one course-isolated AI Study Pack ZIP
```

Each selected course produces an independent `<CourseName>_AI_Study_Pack.zip`.
The package contains source evidence and numbered tutor-control files; it does
not retain a persistent `AI_Knowledge` workspace. Preparation uses no external
AI API, cloud upload, analytics, embeddings, or vector database.

## Trust and privacy boundaries

- Authentication remains between the user and BK-LMS in Chrome.
- Course data, settings, logs, and generated Study Packs remain local.
- Logs redact cookies, authorization headers, and session-related values.
- Downloaded HCMUT material, cookies, session files, credentials, and personal
  information must never be committed to this repository.

For behavioral contracts, see the [AI Study Pack contract](AI_STUDY_PACK_CONTRACT.md)
and the repository [security policy](../SECURITY.md).
