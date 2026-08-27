from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


NAVIGATION_FILES = (
    "START_HERE.md",
    "TUTOR_PROTOCOL.md",
    "COURSE_MAP.md",
    "COVERAGE_REPORT.md",
    "AI_TUTOR_CONTEXT.md",
    "CHATGPT_START_PROMPT.txt",
)
VISUAL_SOURCE_TYPES = {"lecture_pdf", "slide"}
_ABSOLUTE_PATH = re.compile(r"(?im)(?:\b[A-Z]:[\\/]|/(?:Users|home)/)")


@dataclass
class AIStudyPackValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def chapter_numbers(record: dict) -> list[int]:
    values = record.get("chapters")
    if isinstance(values, list):
        numbers = sorted({int(value) for value in values if isinstance(value, int) and value > 0})
        if numbers:
            return numbers
    group = str(record.get("group", ""))
    values = [int(value) for value in re.findall(r"\d+", group)]
    if values:
        return values
    chapter = record.get("chapter")
    return [chapter] if isinstance(chapter, int) and chapter > 0 else []


def chapter_group(record: dict) -> str:
    values = chapter_numbers(record)
    if not values:
        return str(record.get("group", "other"))
    return "chapter_" + "_".join(f"{value:02d}" for value in values)


def chapter_label(values: Iterable[int]) -> str:
    numbers = list(values)
    if not numbers:
        return "Unclassified sources"
    if len(numbers) == 1:
        return f"Chapter {numbers[0]}"
    return "Chapters " + "–".join(str(value) for value in numbers)


def _group_sort_key(group: str) -> tuple[int, tuple[int, ...], str]:
    if group == "00_course":
        return (0, (), group)
    values = tuple(int(value) for value in re.findall(r"\d+", group))
    if group.startswith("chapter_"):
        return (1, values, group)
    if group == "references":
        return (2, (), group)
    return (3, (), group)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _ready_records(records: Iterable[dict]) -> list[dict]:
    return [record for record in records if record.get("status") == "ready"]


def _potential_chapter_gaps(records: Iterable[dict]) -> list[int]:
    values = sorted({number for record in records for number in chapter_numbers(record)})
    if len(values) < 2:
        return []
    return [number for number in range(values[0], values[-1] + 1) if number not in values]


def write_study_navigation(root: Path, course_name: str, records: list[dict]) -> None:
    """Write the concise human/ChatGPT navigation layer from source manifests."""
    root = Path(root)
    ready = _ready_records(records)
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in ready:
        groups[chapter_group(record)].append(record)

    chapter_dir = root / "chapters"
    chapter_paths: dict[str, Path] = {}
    for group in sorted(groups, key=_group_sort_key):
        group_records = sorted(
            groups[group],
            key=lambda record: (int(record.get("order", 0)), str(record.get("title", "")).casefold()),
        )
        values = chapter_numbers(group_records[0])
        if group == "00_course":
            filename = "00_course_overview.md"
            heading = "Course overview and syllabus"
        elif group.startswith("chapter_"):
            filename = group + ".md"
            heading = chapter_label(values)
        elif group == "references":
            filename = "references.md"
            heading = "References"
        else:
            filename = "other_sources.md"
            heading = "Other classified sources"
        path = chapter_dir / filename
        chapter_paths[group] = path
        lines = [f"# {heading}", ""]
        for record in group_records:
            output_path = root / str(record.get("output_path") or "")
            lines.extend(
                (
                    f"## Source: {record.get('title', 'Untitled')}",
                    "",
                    f"- Source ID: `{record.get('source_id', '')}`",
                    f"- Original material: `{record.get('source_path', '')}`",
                    f"- Type: `{record.get('source_type', '')}`",
                    f"- Units: {record.get('units', 0)}",
                    "",
                )
            )
            if output_path.is_file():
                lines.append(output_path.read_text(encoding="utf-8", errors="replace").rstrip())
            else:
                lines.append("_Normalized source document is unavailable._")
            lines.extend(("", "---", ""))
        _write_text(path, "\n".join(lines))

    gaps = _potential_chapter_gaps(ready)
    map_lines = [f"# Course Map — {course_name}", "", "## Source order and modules", ""]
    for group in sorted(groups, key=_group_sort_key):
        group_records = sorted(groups[group], key=lambda record: (int(record.get("order", 0)), str(record.get("title", "")).casefold()))
        values = chapter_numbers(group_records[0])
        label = "Course information" if group == "00_course" else chapter_label(values)
        map_lines.extend((f"## {label}", ""))
        for record in group_records:
            visual = record.get("source_copy_path")
            visual_note = f"; original visual source: `{visual}`" if visual else ""
            map_lines.append(
                f"- `{record.get('source_id', '')}` — {record.get('title', '')} "
                f"({record.get('units', 0)} units; `{record.get('source_path', '')}`{visual_note})"
            )
        if group in chapter_paths:
            map_lines.append(f"- Consolidated teaching evidence: `{chapter_paths[group].relative_to(root).as_posix()}`")
        map_lines.append("")
    if gaps:
        map_lines.extend(("## Potential source gaps", "", f"No downloaded source detected for: Chapter {', '.join(map(str, gaps))}.", ""))
    _write_text(root / "COURSE_MAP.md", "\n".join(map_lines))

    coverage_lines = [f"# Coverage Report — {course_name}", "", "Every discovered source is listed below. A non-READY status is an explicit limitation, not silently omitted.", ""]
    by_status: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_status[str(record.get("status", "unknown")).upper()].append(record)
    for status in sorted(by_status):
        coverage_lines.extend((f"## {status}", ""))
        for record in sorted(by_status[status], key=lambda item: (int(item.get("order", 0)), str(item.get("source_path", "")).casefold())):
            detail = record.get("note") or ""
            coverage_lines.append(
                f"- `{record.get('source_id', '')}` — {record.get('title', '')}; "
                f"`{record.get('source_path', '')}`; {detail}".rstrip("; ")
            )
        coverage_lines.append("")
    if gaps:
        coverage_lines.extend(("## Potential missing chapters", "", f"Chapter {', '.join(map(str, gaps))} was not found in the downloaded materials. No content was invented.", ""))
    _write_text(root / "COVERAGE_REPORT.md", "\n".join(coverage_lines))

    _write_text(
        root / "START_HERE.md",
        f"""# Start here — {course_name}

This is an AI Study Pack created from downloaded course materials. Start with:

1. `COURSE_MAP.md` for source order and chapter mapping.
2. `COVERAGE_REPORT.md` for gaps, duplicates, link-only items, and extraction limits.
3. `TUTOR_PROTOCOL.md` for teaching and problem-solving rules.
4. `chapters/` for long-form teaching evidence with source boundaries.

Use `documents/` for normalized individual sources and `meta/corpus.jsonl` only when chunk-level retrieval is useful. Cite original material as `source_id + page/slide/locator`. Original lecturer PDFs, slides, and retained visual sources are in `sources/` when visual interpretation is needed.

Course-specific facts must follow supplied materials. If evidence is insufficient, say so before adding clearly labelled general knowledge.
""",
    )
    _write_text(
        root / "TUTOR_PROTOCOL.md",
        """# Tutor protocol

## Teach the whole course

1. Read `START_HERE.md`, `COURSE_MAP.md`, and `COVERAGE_REPORT.md` first.
2. Build a roadmap in detected source order. State missing chapters or unresolved sources explicitly.
3. Teach every supplied section of a chapter before marking it complete; preserve lecturer terminology and examples.
4. Use short understanding checks and track the learner's completed chapters.
5. When visual material matters, open the retained original source under `sources/`; do not invent diagram structure from extracted text.

## Answer an exercise or question

1. Locate the relevant chapter and original source.
2. Explain prerequisites first when needed.
3. Solve step-by-step, explain why each step is valid, and check the result.
4. Cite `source_id + locator` and distinguish source-backed guidance from optional general enrichment.

## Evidence limits

If the downloaded materials do not contain enough evidence, say: "Course materials do not contain enough evidence for this part." Generic knowledge may follow only with that limitation clearly labelled.
""",
    )
    _write_text(
        root / "CHATGPT_START_PROMPT.txt",
        """I uploaded an AI Study Pack for one course. First read START_HERE.md, COURSE_MAP.md, COVERAGE_REPORT.md, and TUTOR_PROTOCOL.md. Build a complete roadmap in source order, identify missing chapters or unresolved material, then teach Chapter 1 in detail using lecturer material. Cite source_id plus page/slide/locator, track my completed coverage, and clearly label any knowledge not supported by the supplied course materials.
""",
    )


def _included_pack_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in NAVIGATION_FILES + ("QUALITY_REPORT.md", "links_index.md", "references_index.md", "transcription_queue.md"):
        path = root / name
        if path.is_file():
            paths.append(path)
    for directory in ("chapters", "documents", "chunks", "sources"):
        path = root / directory
        if path.is_dir():
            paths.extend(item for item in path.rglob("*") if item.is_file())
    for name in ("documents.jsonl", "corpus.jsonl", "stats.json", "visual_manifest.json", "study_pack_manifest.json"):
        path = root / "meta" / name
        if path.is_file():
            paths.append(path)
    return sorted(set(paths), key=lambda path: path.as_posix().casefold())


def create_chatgpt_study_pack(root: Path, course_name: str) -> Path:
    """Create a portable, human-first ZIP without logs or absolute source paths."""
    root = Path(root)
    pack_path = root.parent / f"{_safe_filename(course_name)} - AI Study Pack.zip"
    validation = validate_ai_study_pack(root)
    manifest = {
        "format": "BK-LMS AI Study Pack v1",
        "course_name": course_name,
        "included_paths": [path.relative_to(root).as_posix() for path in _included_pack_paths(root)],
        "validation_errors": validation.errors,
        "validation_warnings": validation.warnings,
    }
    _write_text(root / "meta" / "study_pack_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    paths = _included_pack_paths(root)
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(root).as_posix())
    return pack_path


def _safe_filename(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value or "Course")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or "Course"


def _read_jsonl(path: Path, report: AIStudyPackValidation) -> list[dict]:
    records: list[dict] = []
    if not path.is_file():
        report.errors.append(f"Missing manifest: {path.name}")
        return records
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            report.errors.append(f"Malformed JSONL: {path.name} line {line_number}")
    return records


def _is_absolute_metadata_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return Path(value).is_absolute() or bool(_ABSOLUTE_PATH.search(value))


def validate_ai_study_pack(root: Path) -> AIStudyPackValidation:
    """Validate structural, traceability, and privacy invariants deterministically."""
    root = Path(root)
    report = AIStudyPackValidation()
    for name in NAVIGATION_FILES:
        if not (root / name).is_file():
            report.errors.append(f"Missing navigation file: {name}")
    records = _read_jsonl(root / "meta" / "documents.jsonl", report)
    chunks = _read_jsonl(root / "meta" / "corpus.jsonl", report)
    source_ids = {str(record.get("source_id", "")) for record in records}
    ready = _ready_records(records)
    coverage = (root / "COVERAGE_REPORT.md").read_text(encoding="utf-8", errors="replace") if (root / "COVERAGE_REPORT.md").is_file() else ""
    for record in records:
        source_path = str(record.get("source_path", ""))
        if _is_absolute_metadata_path(source_path):
            report.errors.append(f"Absolute source path in manifest: {source_path}")
        for key in ("output_path", "source_copy_path"):
            if _is_absolute_metadata_path(record.get(key)):
                report.errors.append(f"Absolute {key} in manifest: {source_path}")
        if record.get("status") in {"error", "link_only"} and source_path not in coverage:
            report.errors.append(f"Coverage report omits {record.get('status')} source: {source_path}")
        output_path = record.get("output_path")
        if record.get("status") == "ready" and (not output_path or not (root / str(output_path)).is_file()):
            report.errors.append(f"Ready source document missing: {source_path}")
        if record.get("source_type") in VISUAL_SOURCE_TYPES and record.get("status") == "ready":
            copy_path = record.get("source_copy_path")
            if not copy_path or not (root / str(copy_path)).is_file():
                report.errors.append(f"Visual source not retained: {source_path}")
        if record.get("source_type") in VISUAL_SOURCE_TYPES and not chapter_numbers(record):
            report.warnings.append(f"Lecture source has no chapter assignment: {source_path}")
    for chunk in chunks:
        if not chunk.get("source_id"):
            report.errors.append("Chunk without source_id")
        elif str(chunk.get("source_id")) not in source_ids:
            report.errors.append(f"Chunk points to missing source: {chunk.get('source_id')}")
        if not chunk.get("locator"):
            report.errors.append(f"Chunk without locator: {chunk.get('chunk_id', 'unknown')}")
        chunk_path = chunk.get("chunk_path")
        if chunk_path and not (root / str(chunk_path)).is_file():
            report.errors.append(f"Chunk file missing: {chunk_path}")
        for key in ("source_path", "chunk_path"):
            if _is_absolute_metadata_path(chunk.get(key)):
                report.errors.append(f"Absolute {key} in chunk: {chunk.get('chunk_id', 'unknown')}")
    for group in sorted({chapter_group(record) for record in ready if chapter_group(record).startswith("chapter_")}):
        chapter_path = root / "chapters" / f"{group}.md"
        if not chapter_path.is_file():
            report.errors.append(f"Missing chapter document: {group}")
        elif not chapter_path.read_text(encoding="utf-8", errors="replace").strip():
            report.errors.append(f"Empty chapter document: {group}")
    stats_path = root / "meta" / "stats.json"
    if stats_path.is_file():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            if _is_absolute_metadata_path(stats.get("source_root")):
                report.errors.append("Absolute source_root in stats.json")
        except json.JSONDecodeError:
            report.errors.append("Malformed JSON: stats.json")
    visual_path = root / "meta" / "visual_manifest.json"
    if visual_path.is_file():
        try:
            visuals = json.loads(visual_path.read_text(encoding="utf-8"))
            for item in visuals if isinstance(visuals, list) else []:
                if any(_is_absolute_metadata_path(item.get(key)) for key in ("source_path", "copied_path")):
                    report.errors.append("Absolute path in visual_manifest.json")
        except json.JSONDecodeError:
            report.errors.append("Malformed JSON: visual_manifest.json")
    for gap in _potential_chapter_gaps(ready):
        report.warnings.append(f"Potential missing Chapter {gap}: no downloaded source detected")
    return report


def run_ai_study_pack_validator(root: Path) -> int:
    """Print deterministic validation results for source or frozen diagnostic use."""
    report = validate_ai_study_pack(Path(root))
    print(f"AI Study Pack: {Path(root)}")
    print(f"Structural errors: {len(report.errors)}")
    for error in report.errors:
        print(f"ERROR: {error}")
    print(f"Warnings: {len(report.warnings)}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--validate-ai-pack":
        raise SystemExit("Usage: python -m bklms_downloader.ai_study_pack --validate-ai-pack <AI_Knowledge>")
    raise SystemExit(run_ai_study_pack_validator(Path(sys.argv[2])))
