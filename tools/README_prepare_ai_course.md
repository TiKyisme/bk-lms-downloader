# prepare_ai_course.py

This local tool converts one downloaded BK-LMS course into one portable ZIP.
It does not call an AI service, upload data, or create a persistent
`AI_Knowledge` directory.

```text
BK-LMS download -> private temporary extraction/workspace -> one AI Study Pack ZIP
```

## Install

```powershell
pip install beautifulsoup4 markdownify pypdf python-pptx
```

Install `faster-whisper` only when transcription is explicitly needed.

## Run

```powershell
python prepare_ai_course.py `
  --input "D:\University\BK_LMS_Data\Your Course" `
  --output "D:\University\BK_LMS_Data"
```

ZIP input is also supported:

```powershell
python prepare_ai_course.py `
  --input "D:\University\Your Course.zip" `
  --output "D:\University\BK_LMS_Data"
```

The output is named `<CourseName>_AI_Study_Pack.zip`. Existing files are never
deleted; a collision receives a deterministic `_2`, `_3`, and so on suffix.
The old `--force` flag remains accepted for compatibility but does not delete
anything. Passing an output path named `AI_Knowledge` is redirected to its
parent for compatibility and safety.

## Extraction behavior

- `content.txt` is preferred over a duplicate `content.html`.
- Lecture PDFs retain page locators; PPTX files retain slide locators.
- Subtitles retain timestamp locators.
- Untranscribed media, references, URL shortcuts, duplicates, and extraction
  errors remain visible in the source index and coverage tracker.
- Original lecture PDFs/PPTX files are retained under `sources/` when visual
  layout or diagrams may matter.
- Source paths inside metadata are relative; cookies, sessions, and absolute
  developer paths are not included.

## ZIP structure

```text
<CourseName>_AI_Study_Pack.zip
├─ 00_START_HERE.md
├─ 01_COURSE_MAP.md
├─ 02_TUTOR_PROTOCOL.md
├─ 03_SOURCE_INDEX.md
├─ 04_COVERAGE_TRACKER.md
├─ 05_RESUME_STATE.md
├─ chapters/
├─ documents/
├─ chunks/
├─ sources/
└─ meta/
   ├─ corpus.jsonl
   ├─ documents.jsonl
   ├─ stats.json
   ├─ visual_manifest.json
   └─ study_pack_manifest.json
```

`00_START_HERE.md` is the bootstrap contract. It directs the tutor to inspect
the numbered control files and source material, build or validate the roadmap,
start at the first unresolved micro-topic, teach interactively, assess, wait,
debug misconceptions, and track mastery. The ZIP is for one course only.

Validate an unpacked pack with:

```powershell
python -m bklms_downloader.ai_study_pack `
  --validate-ai-pack "D:\University\unpacked-study-pack"
```

The application uses the same pipeline for **Công cụ -> Chuẩn bị cho AI** and
creates one independent ZIP for every selected course. Temporary extraction and
intermediate files are removed after success or failure; completed ZIPs from
earlier courses remain when a later course fails or cancellation is requested.
