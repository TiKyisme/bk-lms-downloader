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

For a genuinely new local settings profile, the GUI can show a guided tutorial
anchored to its actual controls. Valid profiles created before onboarding are
migrated as already onboarded. The Help menu can replay the tutorial and opens
an explicit feedback dialog; feedback is drafted locally and only opens a
user-reviewed GitHub issue page when requested.

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

Optional Coursewave enrichment runs only during an explicit Study Pack update.
It reads public Coursewave/Google Drive metadata, caches verified public exam
payloads locally, and records past Midterm/Final sources separately from
lecturer material. A manifest-enabled refresh can reuse an unchanged compatible
pack, while changed or legacy packs are rebuilt transactionally before atomic
replacement. Coursewave failure never prevents a local-only pack.

## Trust and privacy boundaries

- Authentication remains between the user and BK-LMS in Chrome.
- Course data, settings, logs, and generated Study Packs remain local.
- Logs redact cookies, authorization headers, and session-related values.
- Downloaded HCMUT material, cookies, session files, credentials, and personal
  information must never be committed to this repository.

For behavioral contracts, see the [AI Study Pack contract](AI_STUDY_PACK_CONTRACT.md),
the [Coursewave and past-exam model](COURSEWAVE_EXAMS.md), the [onboarding and feedback model](ONBOARDING_AND_FEEDBACK.md), and the
repository [security policy](../SECURITY.md).
