# Coursewave and past-exam enrichment

Coursewave enrichment is optional. It runs only when the user explicitly
selects **Bổ sung đề thi công khai từ HCMUT Coursewave** while creating or
updating an AI Study Pack.

## Matching and public sources

The app discovers published Coursewave workbook tabs dynamically and aggregates
all public material links for a match. Exact normalized course code is the
primary match. A unique normalized course-name match is a conservative fallback;
ambiguous matches require the user to choose a candidate or skip enrichment.

Only publicly accessible Coursewave/Google Drive links are used. The app never
asks for Google credentials, bypasses permissions, or treats access denial as a
failure of local Study Pack preparation.

For a public Drive folder, the app first uses lightweight HTTP parsing. When a
reachable folder is rendered client-side and exposes no item links in that
response, it uses a bounded Selenium fallback with a disposable incognito
Chrome profile. This isolated browser never reuses the BK-LMS browser, Google
cookies, or a Chrome profile; it closes and its temporary profile is removed
after enumeration. The manifest records `public_enumerated`, `public_empty`,
`permission_denied`, `browser_render_failed`, or `timeout` rather than treating
every outcome as “no exams.”

## Exam scope and cache

Only historical **Midterm** and **Final** material is considered. Folder/path
and file names are normalized for Vietnamese and English exam hints. Unrelated
quizzes, assignments, and exercises are excluded. Public Drive traversal is
bounded by depth and item count.

Catalog metadata, folder metadata, and verified file payloads use separate
per-user local cache entries. Cached payloads are SHA-256 checked before reuse.
No BK-LMS cookies, Google credentials, passwords, or browser tokens are cached.

## AI Study Pack refresh

New packs include versioned `meta/pack_manifest.json`,
`meta/source_manifest.json`, `meta/exam_manifest.json`, and
`06_EXAM_INDEX.md`. An unchanged compatible pack is reused without invoking
source extraction. Legacy packs are safely rebuilt once before receiving the
new manifest format.

Refresh work happens in a temporary workspace. The candidate ZIP is validated
before an atomic replacement of the app-owned existing pack. Cancellation,
network failure, inaccessible Coursewave data, or invalid candidates leave the
previous valid ZIP unchanged.

## Tutor behavior

Lecturer/course materials remain the source of truth. Past exams are marked
`past_exam` and affect assessment style, historical topic emphasis, and question
format only. The tutor must not guarantee exam content, predict an instructor's
questions, or copy historical questions verbatim.

After refreshing a pack, upload the new ZIP again if you are using an older
upload in an existing ChatGPT conversation; the desktop app cannot alter a file
already uploaded to ChatGPT.
