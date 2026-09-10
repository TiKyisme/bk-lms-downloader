# AI Study Pack contract

An AI Study Pack is a local, portable ZIP generated from exactly one downloaded
course. It contains no application settings, cookies, logs, telemetry, cloud
uploads, or absolute private paths. Preparation uses a private temporary
workspace; only the finalized ZIP remains user-visible.

## Required ZIP output

Each selected course produces exactly one independently named archive:

```text
<CourseName>_AI_Study_Pack.zip
```

The application never merges courses. If a course fails, other selected courses
may complete and their ZIPs remain. Cancellation preserves completed archives
and removes the active course's temporary workspace. Existing files are not
overwritten; collisions use a deterministic numeric suffix.

## Authoritative root files

- `00_START_HERE.md` is the bootstrap instruction and tells the tutor to read
  the five other numbered control files, inspect sources, validate/build the
  roadmap, and start at the first unresolved micro-topic.
- `01_COURSE_MAP.md` is generated from detected course sources, source order,
  chapters, sections, gaps, and structural confidence.
- `02_TUTOR_PROTOCOL.md` defines source-grounded interactive teaching:
  Teach -> Assess -> Wait -> Debug -> Re-assess -> Advance, with a mastery gate.
- `03_SOURCE_INDEX.md` maps stable source IDs to relative original names, types,
  chapter information, locators, normalized documents, and retained visuals.
- `04_COVERAGE_TRACKER.md` tracks roadmap/source coverage with not-started,
  in-progress, mastered, weak, source-gap, and skipped states.
- `05_RESUME_STATE.md` defines the compact current chapter, section,
  micro-topic, completed/weak/skipped topics, recent assessments, and next topic.

## Teaching evidence

- `chapters/` contains consolidated, source-boundary-preserving teaching evidence.
- `documents/` contains normalized individual sources; `chunks/` and
  `meta/corpus.jsonl` retain retrieval-level source IDs and locators.
- Original ready lecture PDFs/PPTX files are copied into `sources/` when visual
  layout or diagrams may matter.
- Lecturer/course material has priority over included references, which have
  priority over general model knowledge. Unsupported claims must be labelled
  `[Outside supplied course material]`.
- Missing, duplicate, link-only, media-pending, unsupported, or failed items are
  recorded in the source index and coverage tracker; no content is invented.

## Validation

`validate_ai_study_pack()` and `--validate-ai-pack <unpacked-directory>` reject
missing numbered navigation, malformed manifests, missing source/chunk
references, unretained visual lecture sources, absolute metadata paths, empty
chapter documents, legacy navigation files, and weak bootstrap/protocol rules.
