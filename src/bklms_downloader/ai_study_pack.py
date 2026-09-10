from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


NAVIGATION_FILES = (
    "00_START_HERE.md",
    "01_COURSE_MAP.md",
    "02_TUTOR_PROTOCOL.md",
    "03_SOURCE_INDEX.md",
    "04_COVERAGE_TRACKER.md",
    "05_RESUME_STATE.md",
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
    values = [int(value) for value in re.findall(r"\d+", group) if int(value) > 0]
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


def _public_course_name(value: object) -> str:
    """Keep user-controlled course labels from becoming local-path metadata."""
    text = str(value or "Untitled course").strip()
    text = re.sub(r"(?im)\b[A-Z]:[\\/][^\r\n]*", "[local path]", text)
    text = re.sub(r"(?im)/(?:Users|home)/[^\r\n]*", "[local path]", text)
    return text or "Untitled course"


def _ready_records(records: Iterable[dict]) -> list[dict]:
    return [record for record in records if record.get("status") == "ready"]


def _potential_chapter_gaps(records: Iterable[dict]) -> list[int]:
    values = sorted({number for record in records for number in chapter_numbers(record)})
    if len(values) < 2:
        return []
    return [number for number in range(values[0], values[-1] + 1) if number not in values]


def _source_sections(root: Path, record: dict) -> list[str]:
    """Return headings found in a normalized source without inventing structure."""
    output_path = record.get("output_path")
    if not output_path:
        return []
    path = root / str(output_path)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", text)
        if match.group(1).strip()
    ]


def _chapter_roadmap(groups: dict[str, list[dict]]) -> list[tuple[str, str, list[dict]]]:
    roadmap = []
    for group in sorted(groups, key=_group_sort_key):
        group_records = sorted(
            groups[group],
            key=lambda record: (
                int(record.get("order", 0)),
                str(record.get("title", "")).casefold(),
            ),
        )
        values = chapter_numbers(group_records[0])
        label = "Course information" if group == "00_course" else chapter_label(values)
        roadmap.append((group, label, group_records))
    return roadmap


def write_study_navigation(
    root: Path,
    course_name: str,
    records: list[dict],
    chunks: list[dict] | None = None,
) -> None:
    """Write one authoritative, source-grounded tutor navigation layer."""
    root = Path(root)
    course_name = _public_course_name(course_name)
    ready = _ready_records(records)
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in ready:
        groups[chapter_group(record)].append(record)
    roadmap = _chapter_roadmap(groups)
    gaps = _potential_chapter_gaps(ready)
    unresolved = [record for record in records if record.get("status") != "ready"]
    locators: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks or []:
        source_id = str(chunk.get("source_id", ""))
        locator = str(chunk.get("locator", ""))
        if source_id and locator and locator not in locators[source_id]:
            locators[source_id].append(locator)

    if not ready:
        confidence = "Low — no source was successfully normalized."
    elif unresolved or gaps:
        confidence = "Medium — usable sources exist, but unresolved material or gaps remain."
    else:
        confidence = "High — all discovered sources were normalized without detected gaps."

    map_lines = [
        f"# Course Map — {course_name}",
        "",
        "This roadmap is generated from this course's downloaded materials. It is not a generic template.",
        "",
        f"Structural confidence: **{confidence}**",
        "",
        "## Detected learning order",
        "",
    ]
    chapter_dir = root / "chapters"
    chapter_paths: dict[str, Path] = {}
    for group, label, group_records in roadmap:
        if group == "00_course":
            filename = "00_course_overview.md"
        elif group.startswith("chapter_"):
            filename = group + ".md"
        elif group == "references":
            filename = "references.md"
        else:
            filename = "other_sources.md"
        chapter_path = chapter_dir / filename
        chapter_paths[group] = chapter_path
        chapter_lines = [f"# {label}", "", "Teaching evidence from this course's supplied sources.", ""]
        for record in group_records:
            chapter_lines.extend(
                (
                    f"## {record.get('title', 'Untitled')}",
                    "",
                    f"Source ID: `{record.get('source_id', '')}`",
                    f"Original material: `{record.get('source_path', '')}`",
                    "",
                )
            )
            output_path = root / str(record.get("output_path") or "")
            if output_path.is_file():
                chapter_lines.append(output_path.read_text(encoding="utf-8", errors="replace").rstrip())
            else:
                chapter_lines.append("_Normalized source document is unavailable._")
            chapter_lines.extend(("", "---", ""))
        _write_text(chapter_path, "\n".join(chapter_lines))

    if not roadmap:
        map_lines.append("_No ready course material was detected._")
    for group, label, group_records in roadmap:
        map_lines.extend((f"### {label}", ""))
        for record in group_records:
            source_id = record.get("source_id", "")
            title = record.get("title", "Untitled")
            sections = _source_sections(root, record)
            map_lines.append(f"- `{source_id}` — {title}")
            if sections:
                map_lines.append(f"  - Detected sections: {', '.join(sections[:20])}")
            map_lines.append(
                f"  - Evidence: `{record.get('output_path', '')}`; "
                f"{record.get('units', 0)} source units"
            )
        map_lines.append(
            f"- Consolidated teaching evidence: `{chapter_paths[group].relative_to(root).as_posix()}`"
        )
        map_lines.append("")
    if gaps:
        map_lines.extend(
            (
                "## Potential source gaps",
                "",
                f"No downloaded source was detected for: Chapter {', '.join(map(str, gaps))}.",
                "Do not invent the missing content; mark it as `[?] SOURCE GAP`.",
                "",
            )
        )
    _write_text(root / "01_COURSE_MAP.md", "\n".join(map_lines))

    source_lines = [
        f"# Source Index — {course_name}",
        "",
        "Stable source IDs are the citation anchors for this one-course package.",
        "Absolute local paths, cookies, and session data are intentionally excluded.",
        "",
    ]
    for record in sorted(
        records,
        key=lambda item: (int(item.get("order", 0)), str(item.get("source_path", "")).casefold()),
    ):
        source_lines.extend(
            (
                f"## `{record.get('source_id', '')}` — {record.get('title', 'Untitled')}",
                "",
                f"- Original material: `{record.get('source_path', '')}`",
                f"- Type: `{record.get('source_type', '')}`",
                f"- Chapter: `{chapter_label(chapter_numbers(record))}`",
                f"- Status: `{record.get('status', 'unknown')}`",
                f"- Units: {record.get('units', 0)}",
            )
        )
        if record.get("output_path"):
            source_lines.append(f"- Normalized source: `{record['output_path']}`")
        if record.get("source_copy_path"):
            source_lines.append(f"- Retained visual source: `{record['source_copy_path']}`")
        if locators.get(str(record.get("source_id", ""))):
            source_lines.append(
                "- Locators: " + ", ".join(f"`{locator}`" for locator in locators[record["source_id"]][:30])
            )
        if record.get("note"):
            source_lines.append(f"- Note: {record['note']}")
        source_lines.append("")
    _write_text(root / "03_SOURCE_INDEX.md", "\n".join(source_lines))

    coverage_lines = [
        f"# Coverage Tracker — {course_name}",
        "",
        "This is the initial course-coverage and tutoring-progress contract.",
        "The tutor must update progress in conversation or in a safe writable copy.",
        "",
        "## Status legend",
        "",
        "- `[ ]` Not started",
        "- `[~]` In progress",
        "- `[✓]` Mastered",
        "- `[!]` Weak",
        "- `[?]` Source gap",
        "- `[-]` Skipped",
        "",
        "## Roadmap progress",
        "",
    ]
    for group, label, group_records in roadmap:
        source_ids = ", ".join(f"`{record.get('source_id', '')}`" for record in group_records)
        coverage_lines.append(f"- `[ ]` {label} — sources: {source_ids}")
    for gap in gaps:
        coverage_lines.append(f"- `[?]` Chapter {gap} — SOURCE GAP")
    if not roadmap and not gaps:
        coverage_lines.append("- `[?]` No usable roadmap could be generated from the supplied material.")
    coverage_lines.extend(("", "## Source coverage", ""))
    for record in records:
        status = "[ ]" if record.get("status") == "ready" else "[?]"
        detail = record.get("note") or record.get("status", "unresolved")
        coverage_lines.append(
            f"- `{status}` `{record.get('source_id', '')}` — {record.get('source_path', '')} ({detail})"
        )
    if unresolved:
        coverage_lines.extend(
            (
                "",
                "## Unresolved material",
                "",
                "The following items were discovered but were not fully available for teaching:",
                "",
            )
        )
        for record in unresolved:
            coverage_lines.append(
                f"- `[?]` `{record.get('source_id', '')}` — {record.get('source_path', '')}: "
                f"{record.get('note') or record.get('status', 'unresolved')}"
            )
    _write_text(root / "04_COVERAGE_TRACKER.md", "\n".join(coverage_lines))

    _write_text(
        root / "00_START_HERE.md",
        f"""# Start here — {course_name}

This ZIP is a self-contained AI Study Pack for **one course only**: **{course_name}**.
Read this file first, then immediately inspect:

1. `01_COURSE_MAP.md`
2. `02_TUTOR_PROTOCOL.md`
3. `03_SOURCE_INDEX.md`
4. `04_COVERAGE_TRACKER.md`
5. `05_RESUME_STATE.md`

Next inspect the supplied lecturer/course materials under `sources/`, `documents/`, and `chapters/`.
Use the source index and `meta/corpus.jsonl` to trace every teaching claim to a stable `source_id` and an available page, slide, timestamp, or other locator.

Build or validate the complete roadmap in source order and detect missing or unresolved material before teaching. Do not ask the learner what they want to study, which chapter to start, or how you can help. If there is no previous progress, begin automatically with the first unresolved micro-topic.

In the first teaching response, briefly show the high-level roadmap and current position, then teach that first micro-topic and ask an understanding check. Do not dump an entire chapter of theory. Follow `02_TUTOR_PROTOCOL.md` exactly and stop after the assessment so the learner can respond.
""",
    )
    _write_text(
        root / "02_TUTOR_PROTOCOL.md",
        """# Interactive tutor protocol

## Mission

Teach for understanding from this course's supplied materials. This is an interactive tutor, not a textbook summarizer and not a generator of a whole-course theory dump.

## Source grounding

Use this evidence hierarchy:

1. lecturer/course material;
2. official course references included in this pack;
3. supplementary included references;
4. general model knowledge only when necessary.

Preserve lecturer order, terminology, formulas, examples, and stated scope. Cite a stable `source_id` plus the closest locator actually present, such as page, slide, timestamp, or section. Never invent citations, page numbers, slide numbers, definitions, or formulas. If a claim is not supported by the supplied material, label it exactly as `[Outside supplied course material]` before using it. Do not silently mix outside knowledge into course teaching.

## Automatic first response

After reading the five numbered control files and the source material, construct or validate the complete roadmap and identify source gaps. Do not ask what to study or which chapter to start. Briefly show the high-level roadmap and current position, then automatically begin the first unresolved micro-topic. If progress exists, resume at the first unresolved topic.

Use the language of the supplied course materials by default. If most material is Vietnamese, teach in Vietnamese while preserving useful English technical terms; if most material is English, follow that convention.

## Learning loop

Repeat this loop for one small coherent micro-topic at a time:

1. **TEACH** — explain the idea for understanding: why it exists, what it means, how it works, relationships, contrasts with commonly confused concepts, one concrete example, useful intuition, and relevant edge cases or traps. Adapt the explanation to the subject and source evidence; do not force irrelevant headings.
2. **ASSESS** — immediately ask approximately one to three questions using varied self-explanation, MCQ, application, prediction, comparison, or calculation formats. Use plausible misconception-based distractors when appropriate.
3. **WAIT** — stop after asking. Do not reveal the answer, grade the question yourself, or continue to the next topic before the learner responds.
4. **DEBUG** — analyze the learner's reasoning, not only the final answer. Identify missing concepts, misconceptions, lucky guesses, terminology confusion, and reasoning errors. A correct choice with faulty reasoning is not mastery.
5. **RE-ASSESS** — reteach only the weak part using a new example, analogy, counterexample, diagram description, or comparison, then ask a new question testing the same underlying concept.
6. **ADVANCE** — move on only after the core concept and important relationships are demonstrated.

## Mastery and coverage

Use a default mastery target of at least 80%, unless course-specific rules in the supplied material define another threshold, but do not rely on raw score alone. A topic is mastered only when its core concept, important relationship, and reasoning are sound with no major misconception. Use `[ ]` not started, `[~]` in progress, `[✓]` mastered, `[!]` weak, `[?]` source gap, and `[-]` skipped. If the learner skips, mark it `[-] [SKIPPED / WEAK]`; never call it mastered.

Track coverage by chapter, section, source ID, and locator. A section cannot be mastered until its required supplied concepts have been taught and assessed. After all micro-topics in a section, run a short integration check. At chapter completion, provide a concise conceptual map, key relationships, observed weak points, common traps, and a short mastery quiz—not a huge generic summary.

## Adaptation and resume

Increase application difficulty and reduce repetition when reasoning is consistently strong. If the learner struggles, reduce topic size, reteach prerequisites, and increase retrieval practice. Keep progress in `05_RESUME_STATE.md` when a writable copy is available; otherwise maintain it in conversation and show a compact resume block at section/chapter/session checkpoints, not after every tiny message.

## Hard prohibitions

Do not theory-dump an entire chapter, silently skip source material, invent missing lecturer content, reveal assessment answers before the learner responds, or advance solely because an MCQ letter was correct. Do not provide a full homework solution when guided reasoning is the appropriate teaching method.
""",
    )
    _write_text(
        root / "05_RESUME_STATE.md",
        f"""# Resume state — {course_name}

This package starts with no learner-specific progress unless the learner supplies an updated writable copy.

```text
Course: {course_name}
Current chapter: Not started
Current section: Not started
Current micro-topic: First unresolved topic from 01_COURSE_MAP.md
Completed topics: None
Weak topics: None
Skipped topics: None
Recent assessment results: None
Next topic: First unresolved topic from 01_COURSE_MAP.md
```

When resuming, trust the most recent explicit learner progress, verify it against `04_COVERAGE_TRACKER.md`, and do not mark a topic mastered without demonstrated reasoning.
""",
    )


def _included_pack_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in NAVIGATION_FILES:
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


def _next_pack_path(destination_dir: Path, course_name: str) -> Path:
    """Choose a deterministic non-destructive path for a generated archive."""
    stem = f"{_safe_filename(_public_course_name(course_name))}_AI_Study_Pack"
    candidate = destination_dir / f"{stem}.zip"
    index = 2
    while candidate.exists():
        candidate = destination_dir / f"{stem}_{index}.zip"
        index += 1
    return candidate


def create_chatgpt_study_pack(
    root: Path,
    course_name: str,
    destination_dir: Path | None = None,
) -> Path:
    """Create one portable ZIP, atomically and without overwriting existing files."""
    root = Path(root).resolve()
    destination = Path(destination_dir or root.parent).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    validation = validate_ai_study_pack(root)
    if validation.errors:
        raise RuntimeError("AI Study Pack validation failed: " + "; ".join(validation.errors))

    pack_path = _next_pack_path(destination, course_name)
    manifest = {
        "format": "BK-LMS AI Study Pack v2",
        "course_name": _public_course_name(course_name),
        "one_course_only": True,
        "included_paths": [path.relative_to(root).as_posix() for path in _included_pack_paths(root)],
        "validation_errors": [],
        "validation_warnings": validation.warnings,
    }
    _write_text(root / "meta" / "study_pack_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    paths = _included_pack_paths(root)
    with tempfile.NamedTemporaryFile(
        prefix=f".{pack_path.name}.",
        suffix=".zip.part",
        dir=destination,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, path.relative_to(root).as_posix())
        temporary.replace(pack_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
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
    legacy_paths = (
        "START_HERE.md",
        "COURSE_MAP.md",
        "TUTOR_PROTOCOL.md",
        "COVERAGE_REPORT.md",
        "AI_TUTOR_CONTEXT.md",
        "CHATGPT_START_PROMPT.txt",
        "AI_Knowledge",
    )
    for name in legacy_paths:
        if (root / name).exists():
            report.errors.append(f"Legacy study-pack output present: {name}")
    start_path = root / "00_START_HERE.md"
    protocol_path = root / "02_TUTOR_PROTOCOL.md"
    if start_path.is_file():
        start_text = start_path.read_text(encoding="utf-8", errors="replace").casefold()
        for phrase in ("first unresolved", "do not ask", "understanding check"):
            if phrase not in start_text:
                report.errors.append(f"Bootstrap missing rule: {phrase}")
    if protocol_path.is_file():
        protocol_text = protocol_path.read_text(encoding="utf-8", errors="replace").casefold()
        for phrase in (
            "teach",
            "assess",
            "wait",
            "debug",
            "re-assess",
            "mastery",
            "coverage",
            "source_id",
            "theory dump",
            "before the learner responds",
        ):
            if phrase not in protocol_text:
                report.errors.append(f"Tutor protocol missing rule: {phrase}")
    records = _read_jsonl(root / "meta" / "documents.jsonl", report)
    chunks = _read_jsonl(root / "meta" / "corpus.jsonl", report)
    source_ids = {str(record.get("source_id", "")) for record in records}
    ready = _ready_records(records)
    coverage = (root / "04_COVERAGE_TRACKER.md").read_text(encoding="utf-8", errors="replace") if (root / "04_COVERAGE_TRACKER.md").is_file() else ""
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
        raise SystemExit("Usage: python -m bklms_downloader.ai_study_pack --validate-ai-pack <study-pack-directory>")
    raise SystemExit(run_ai_study_pack_validator(Path(sys.argv[2])))
