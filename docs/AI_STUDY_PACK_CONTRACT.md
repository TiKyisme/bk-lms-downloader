# AI Study Pack contract

An AI Study Pack is a local, portable package generated from one downloaded
course. It is designed for a student to upload to ChatGPT or another assistant
without sharing application settings, cookies, logs, or absolute local paths.

## Required navigation

- `START_HERE.md` explains reading order and evidence rules.
- `COURSE_MAP.md` maps source order to chapters/modules and points to retained
  original visual sources.
- `COVERAGE_REPORT.md` accounts for every discovered source as READY, DUPLICATE,
  LINK_ONLY, REFERENCE_INDEXED_ONLY, MEDIA_PENDING, SKIPPED, or ERROR.
- `TUTOR_PROTOCOL.md` defines evidence-first teaching and problem-solving rules.
- `CHATGPT_START_PROMPT.txt` is the short prompt a student can paste after upload.

## Teaching evidence

- `chapters/` contains lossless, source-boundary-preserving consolidated Markdown
  for course overview and every detected chapter/range.
- `documents/` retains normalized individual sources; `chunks/` and
  `meta/corpus.jsonl` retain retrieval-level traceability.
- Every chunk has a source ID and locator. Course-specific claims should cite
  `source_id + page/slide/locator`.
- Original ready lecture PDFs/PPTX files are copied into `sources/` and mapped by
  `meta/visual_manifest.json` so diagrams and layout-dependent meaning remain
  accessible. Text extraction alone is not treated as complete visual coverage.

## Coverage honesty

- Chapter ranges such as `Ch3_4` are stored as `chapters: [3, 4]` and grouped as
  `chapter_03_04`.
- Numbering gaps are reported as possible missing downloaded materials; no
  chapter content is invented.
- URL shortcuts are marked LINK_ONLY unless their authorized target was actually
  downloaded.

## Validation

`validate_ai_study_pack()` and `--validate-ai-pack <AI_Knowledge>` return a
non-zero status for missing navigation, malformed manifests, missing source/chunk
references, unretained visual lecture sources, absolute metadata paths, or empty
chapter documents. Potential chapter gaps and genuinely unclassified lecture
sources remain warnings.
