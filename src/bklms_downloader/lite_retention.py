"""Fail-closed local duplicate-representation retention for AI Study Packs."""
from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz
from PIL import Image
from pptx import Presentation

MIN_PPTX_PDF_SAVING_BYTES = 1024 * 1024
MIN_PPTX_PDF_SAVING_RATIO = 0.10
MIN_PPTX_SOURCE_BYTES = 1024 * 1024
TARGET_PACK_BYTES = 95_000_000
HARD_PACK_BYTES = 100_000_000
PDF_TEXT_PAGE_MIN_CHARS = 200
PDF_LOW_TEXT_CHARS = 80
PDF_MAX_DRAWINGS_PER_PAGE = 20


@dataclass(frozen=True)
class EquivalenceResult:
    verdict: str = "UNVERIFIED"
    matched_count: int = 0
    left_count: int = 0
    right_count: int = 0
    mean_visual_distance: float | None = None
    max_visual_distance: int | None = None
    reason: str = "verification_failed"


def _hash_page(page) -> int:
    pix = page.get_pixmap(matrix=fitz.Matrix(0.25, 0.25), alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L").resize((9, 8))
    pixels = list(image.getdata())
    return sum(1 << index for index, (a, b) in enumerate(zip(
        [pixels[row * 9 + col] for row in range(8) for col in range(8)],
        [pixels[row * 9 + col + 1] for row in range(8) for col in range(8)],
    )) if a > b)


def _pptx_to_pdf(source: Path, destination: Path) -> None:
    import win32com.client
    app = None
    presentation = None
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(source.resolve()), WithWindow=False)
        presentation.SaveAs(str(destination.resolve()), 32)
    finally:
        if presentation is not None:
            presentation.Close()
        if app is not None:
            app.Quit()


def _pptx_to_pdf_and_images(source: Path, pdf_destination: Path, image_directory: Path) -> int:
    """One isolated PowerPoint session produces both comparison views and PDF."""
    import win32com.client
    app = presentation = None
    try:
        image_directory.mkdir(parents=True, exist_ok=True)
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(source.resolve()), WithWindow=False)
        count = presentation.Slides.Count
        presentation.SaveAs(str(pdf_destination.resolve()), 32)
        for index in range(1, count + 1):
            presentation.Slides(index).Export(str((image_directory / f"slide_{index:04}.png").resolve()), "PNG", 1280, 720)
        return count
    finally:
        if presentation is not None:
            presentation.Close()
        if app is not None:
            app.Quit()


def verify_pptx_pdf(pptx: Path, pdf: Path) -> EquivalenceResult:
    try:
        source_slide_count = len(Presentation(pptx).slides)
        with tempfile.TemporaryDirectory(prefix="bklms_lite_verify_") as temporary:
            converted = Path(temporary) / "deck.pdf"
            _pptx_to_pdf(pptx, converted)
            with fitz.open(converted) as left, fitz.open(pdf) as right:
                left_count, right_count = len(left), len(right)
                if source_slide_count != left_count or left_count != right_count or not left_count:
                    return EquivalenceResult(left_count=source_slide_count, right_count=right_count, reason="page_count_mismatch")
                distances = [(_hash_page(left[index]) ^ _hash_page(right[index])).bit_count() for index in range(left_count)]
            if any(distance > 8 for distance in distances):
                return EquivalenceResult("NOT_EQUIVALENT", sum(d <= 8 for d in distances), left_count, right_count, sum(distances) / len(distances), max(distances), "visual_distance_exceeded")
            return EquivalenceResult("FULL_EQUIVALENCE", left_count, left_count, right_count, round(sum(distances) / len(distances), 2), max(distances), "all_pages_visually_equivalent")
    except Exception as exc:
        return EquivalenceResult(reason=f"{type(exc).__name__}")


def verify_pptx_only_conversion(pptx: Path, pdf_destination: Path) -> EquivalenceResult:
    """Fail closed unless exported PDF preserves every slide's rendered view."""
    try:
        source_slide_count = len(Presentation(pptx).slides)
        with tempfile.TemporaryDirectory(prefix="bklms_lite_convert_") as temporary:
            image_directory = Path(temporary) / "slides"
            exported_count = _pptx_to_pdf_and_images(pptx, pdf_destination, image_directory)
            with fitz.open(pdf_destination) as pdf:
                page_count = len(pdf)
                if source_slide_count != exported_count or exported_count != page_count or not page_count:
                    return EquivalenceResult(left_count=source_slide_count, right_count=page_count, reason="page_count_mismatch")
                distances = []
                for index in range(1, page_count + 1):
                    image = Image.open(image_directory / f"slide_{index:04}.png").convert("L").resize((9, 8))
                    pixels = list(image.getdata())
                    slide_hash = sum(1 << bit for bit, (a, b) in enumerate(zip(
                        [pixels[row * 9 + column] for row in range(8) for column in range(8)],
                        [pixels[row * 9 + column + 1] for row in range(8) for column in range(8)],
                    )) if a > b)
                    distances.append((slide_hash ^ _hash_page(pdf[index - 1])).bit_count())
            if any(distance > 8 for distance in distances):
                return EquivalenceResult("NOT_EQUIVALENT", sum(d <= 8 for d in distances), source_slide_count, page_count, sum(distances) / len(distances), max(distances), "visual_distance_exceeded")
            return EquivalenceResult("FULL_EQUIVALENCE", page_count, source_slide_count, page_count, round(sum(distances) / len(distances), 2), max(distances), "all_slides_visually_equivalent")
    except Exception as exc:
        pdf_destination.unlink(missing_ok=True)
        return EquivalenceResult(reason=f"{type(exc).__name__}")


def _normalized_text(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(re.sub(r"\W+", " ", text).casefold().split())


def _text_similarity(left: Path, right: Path) -> float:
    a, b = _normalized_text(left), _normalized_text(right)
    return len(a & b) / max(1, len(a | b))


def _workspace_zip_size(root: Path) -> int:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                archive.write(path, path.relative_to(root).as_posix())
        return temporary.stat().st_size
    finally:
        temporary.unlink(missing_ok=True)


def analyze_pdf_visual(path: Path) -> dict:
    """Fail-closed page-level evidence for lecturer PDF retention."""
    try:
        with fitz.open(path) as document:
            text_dominant = low_text = zero_text = image_pages = drawing_pages = 0
            for number, page in enumerate(document, 1):
                text_chars = len(page.get_text().strip())
                if text_chars >= PDF_TEXT_PAGE_MIN_CHARS: text_dominant += 1
                if text_chars < PDF_LOW_TEXT_CHARS: low_text += 1
                if not text_chars: zero_text += 1
                has_images = bool(page.get_images(full=True)); has_drawings = len(page.get_drawings()) > PDF_MAX_DRAWINGS_PER_PAGE
                if has_images: image_pages += 1
                if has_drawings: drawing_pages += 1
            pages = len(document)
        verdict = "TEXT_DOMINANT" if pages and text_dominant == pages and not low_text and not image_pages and not drawing_pages else "VISUAL_REQUIRED"
        return {"page_count": pages, "text_dominant_pages": text_dominant, "zero_text_pages": zero_text, "low_text_pages": low_text, "image_heavy_pages": image_pages, "drawing_heavy_pages": drawing_pages, "verdict": verdict}
    except Exception as exc:
        return {"page_count": 0, "verdict": "UNCERTAIN", "error": type(exc).__name__}


def optimize_workspace(root: Path, records: list) -> list[dict]:
    """Remove only verified full duplicates; every failure keeps both binaries."""
    retention_path = root / "meta" / "lite_retention.json"
    try:
        existing = json.loads(retention_path.read_text(encoding="utf-8")).get("sources", [])
    except (OSError, ValueError, AttributeError):
        existing = []
    candidates = []
    for left in records:
        left_copy = getattr(left, "source_copy_path", None)
        left_doc = getattr(left, "output_path", None)
        if not left_copy or not left_doc or Path(left_copy).suffix.lower() != ".pptx":
            continue
        for right in records:
            right_copy = getattr(right, "source_copy_path", None)
            right_doc = getattr(right, "output_path", None)
            if not right_copy or not right_doc or Path(right_copy).suffix.lower() != ".pdf":
                continue
            similarity = _text_similarity(root / left_doc, root / right_doc)
            if similarity >= 0.70:
                candidates.append((similarity, left, right))
    decisions = [item for item in existing if isinstance(item, dict)]
    used = set()
    full_equivalent_pptx = set()
    for similarity, left, right in sorted(candidates, key=lambda item: item[0], reverse=True):
        if left.source_id in used or right.source_id in used:
            continue
        left_path, right_path = root / left.source_copy_path, root / right.source_copy_path
        try:
            evidence = verify_pptx_pdf(left_path, right_path)
        except Exception:
            continue
        if evidence.verdict != "FULL_EQUIVALENCE":
            continue
        left_cost = len(zlib.compress(left_path.read_bytes(), 9)); right_cost = len(zlib.compress(right_path.read_bytes(), 9))
        omitted, retained = (left, right) if left_cost > right_cost else (right, left)
        omitted_path = root / omitted.source_copy_path
        decisions.append({"source_id": omitted.source_id, "decision": "OMIT_VERIFIED_DUPLICATE", "represented_by": retained.source_id, "text_similarity": round(similarity, 4), "equivalence": asdict(evidence)})
        omitted.source_copy_path = None
        omitted.represented_by_source_id = retained.source_id
        omitted.retention_decision = "OMIT_VERIFIED_DUPLICATE"
        omitted_path.unlink()
        full_equivalent_pptx.add(left.source_id)
        used.update((left.source_id, right.source_id))
    # A merely related PDF is not proof that the PPTX is represented. Only a
    # verified full-equivalence pair is ineligible for its own conversion.
    related_pptx = full_equivalent_pptx
    for record in records:
        copy_path = getattr(record, "source_copy_path", None)
        if not copy_path or record.source_id in related_pptx or Path(copy_path).suffix.lower() != ".pptx":
            continue
        source = root / copy_path
        if source.stat().st_size < MIN_PPTX_SOURCE_BYTES:
            continue
        retained = source.with_suffix(".pdf")
        evidence = verify_pptx_only_conversion(source, retained)
        original_cost = len(zlib.compress(source.read_bytes(), 9))
        retained_cost = len(zlib.compress(retained.read_bytes(), 9)) if retained.is_file() else original_cost
        saving = original_cost - retained_cost
        if evidence.verdict != "FULL_EQUIVALENCE" or saving < MIN_PPTX_PDF_SAVING_BYTES or saving / max(1, original_cost) < MIN_PPTX_PDF_SAVING_RATIO:
            retained.unlink(missing_ok=True)
            continue
        source.unlink()
        record.source_copy_path = retained.relative_to(root).as_posix()
        record.retention_decision = "REPLACE_WITH_VERIFIED_PDF"
        decisions.append({"source_id": record.source_id, "decision": "REPLACE_WITH_VERIFIED_PDF", "original_format": "pptx", "retained_format": "pdf", "original_slide_count": evidence.left_count, "retained_page_count": evidence.right_count, "original_zip_cost": original_cost, "retained_zip_cost": retained_cost, "saving_bytes": saving, "verification": asdict(evidence)})
    for record in records:
        copy_path = getattr(record, "source_copy_path", None)
        if not copy_path or Path(copy_path).suffix.lower() != ".pdf" or getattr(record, "source_type", "") != "lecture_pdf":
            continue
        original = root / copy_path
        original_cost = len(zlib.compress(original.read_bytes(), 9))
        analysis = analyze_pdf_visual(root / copy_path)
        if not getattr(record, "output_path", None) or not (root / record.output_path).is_file():
            continue
        original_cost = len(zlib.compress(original.read_bytes(), 9))
        if analysis.get("verdict") == "TEXT_DOMINANT":
            original.unlink(); record.source_copy_path = None; record.retention_decision = "MARKDOWN_SUFFICIENT"
            decisions.append({"source_id": record.source_id, "decision": "MARKDOWN_SUFFICIENT", "original_format": "pdf", "original_zip_cost": original_cost, "normalized_document": record.output_path, "analysis": analysis})
    # Final compact pass: remove only copied lecturer binaries whose normalized
    # document remains. This is budget pressure, never visual evidence proof.
    projected_size = _workspace_zip_size(root)
    if projected_size > TARGET_PACK_BYTES:
        removable = []
        for record in records:
            copy_path = getattr(record, "source_copy_path", None)
            if not copy_path or getattr(record, "source_type", "") not in {"lecture_pdf", "slide"} or not getattr(record, "output_path", None):
                continue
            binary = root / copy_path; document = root / record.output_path
            if binary.is_file() and document.is_file(): removable.append((len(zlib.compress(binary.read_bytes(), 9)), record, binary))
        for _cost, record, binary in sorted(removable, reverse=True, key=lambda item: item[0]):
            if projected_size <= TARGET_PACK_BYTES: break
            analysis = analyze_pdf_visual(binary) if binary.suffix.lower() == ".pdf" else {"verdict": "VISUAL_REQUIRED"}
            decision = "OMIT_BINARY_SIZE_BUDGET" if analysis.get("verdict") == "TEXT_DOMINANT" else "OMIT_VISUAL_BINARY_SIZE_BUDGET"
            binary.unlink()
            projected_size -= _cost
            record.source_copy_path = None; record.retention_decision = decision
            decisions.append({"source_id": record.source_id, "decision": decision, "original_format": binary.suffix.lower().lstrip("."), "original_zip_cost": _cost, "normalized_document": record.output_path, "reason": "pack_size_budget", "analysis": analysis})
    (root / "meta").mkdir(exist_ok=True)
    retention_path.write_text(json.dumps({"retention_mode": "lite-v1", "sources": decisions}, indent=2), encoding="utf-8")
    return decisions
