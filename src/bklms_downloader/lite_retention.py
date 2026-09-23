"""Fail-closed local duplicate-representation retention for AI Study Packs."""
from __future__ import annotations

import io
import json
import re
import tempfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz
from PIL import Image
from pptx import Presentation


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


def _normalized_text(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(re.sub(r"\W+", " ", text).casefold().split())


def _text_similarity(left: Path, right: Path) -> float:
    a, b = _normalized_text(left), _normalized_text(right)
    return len(a & b) / max(1, len(a | b))


def optimize_workspace(root: Path, records: list) -> list[dict]:
    """Remove only verified full duplicates; every failure keeps both binaries."""
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
    decisions = []
    used = set()
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
        used.update((left.source_id, right.source_id))
    (root / "meta").mkdir(exist_ok=True)
    (root / "meta" / "lite_retention.json").write_text(json.dumps({"retention_mode": "lite-v1", "sources": decisions}, indent=2), encoding="utf-8")
    return decisions
