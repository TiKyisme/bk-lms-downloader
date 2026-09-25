import json
import os
from pathlib import Path
from types import SimpleNamespace

import bklms_downloader.lite_retention as lite


def record(source_id, copy, doc):
    return SimpleNamespace(source_id=source_id, source_copy_path=copy, output_path=doc, represented_by_source_id=None, retention_decision=None)


def workspace(tmp_path):
    (tmp_path/"sources").mkdir(); (tmp_path/"documents").mkdir(); (tmp_path/"meta").mkdir()
    (tmp_path/"sources/a.pptx").write_bytes(b"A"*5000); (tmp_path/"sources/unrelated-name.pdf").write_bytes(b"B"*1000)
    for name in ("a.md","b.md"): (tmp_path/"documents"/name).write_text("identical instructional content "*20,encoding="utf-8")
    return [record("left","sources/a.pptx","documents/a.md"),record("right","sources/unrelated-name.pdf","documents/b.md")]


def test_full_equivalence_omits_larger_binary_and_keeps_traceability(monkeypatch,tmp_path):
    records=workspace(tmp_path)
    monkeypatch.setattr(lite,"verify_pptx_pdf",lambda *_: lite.EquivalenceResult("FULL_EQUIVALENCE",10,10,10,1.0,2,"verified"))
    decisions=lite.optimize_workspace(tmp_path,records)
    assert len(decisions)==1 and not (tmp_path/"sources/a.pptx").exists()
    assert records[0].represented_by_source_id=="right"
    assert json.loads((tmp_path/"meta/lite_retention.json").read_text())["sources"][0]["represented_by"]=="right"


def test_unverified_changed_or_exception_keeps_both(monkeypatch,tmp_path):
    records=workspace(tmp_path)
    monkeypatch.setattr(lite,"verify_pptx_pdf",lambda *_: lite.EquivalenceResult("NOT_EQUIVALENT",reason="changed"))
    assert lite.optimize_workspace(tmp_path,records)==[]
    assert (tmp_path/"sources/a.pptx").exists() and (tmp_path/"sources/unrelated-name.pdf").exists()


def test_verifier_exception_keeps_both(monkeypatch,tmp_path):
    records=workspace(tmp_path)
    monkeypatch.setattr(lite,"verify_pptx_pdf",lambda *_: (_ for _ in ()).throw(RuntimeError("failed")))
    lite.optimize_workspace(tmp_path,records)
    assert (tmp_path/"sources/a.pptx").exists() and (tmp_path/"sources/unrelated-name.pdf").exists()


def test_powerpoint_unavailable_is_conservative(monkeypatch, tmp_path):
    monkeypatch.setattr(lite, "Presentation", lambda _path: SimpleNamespace(slides=[object()]))
    monkeypatch.setattr(lite, "_pptx_to_pdf", lambda *_: (_ for _ in ()).throw(RuntimeError("PowerPoint unavailable")))
    result = lite.verify_pptx_pdf(tmp_path / "deck.pptx", tmp_path / "deck.pdf")
    assert result.verdict == "UNVERIFIED"
    assert result.reason == "RuntimeError"


def test_pptx_only_verified_conversion_replaces_source(monkeypatch, tmp_path):
    (tmp_path / "sources").mkdir(); (tmp_path / "documents").mkdir(); (tmp_path / "meta").mkdir()
    (tmp_path / "sources/deck.pptx").write_bytes(os.urandom(2 * 1024 * 1024))
    (tmp_path / "documents/deck.md").write_text("unique deck", encoding="utf-8")
    item = record("deck", "sources/deck.pptx", "documents/deck.md")
    def convert(_source, destination):
        destination.write_bytes(b"B" * 1024)
        return lite.EquivalenceResult("FULL_EQUIVALENCE", 2, 2, 2, 1.0, 2, "verified")
    monkeypatch.setattr(lite, "verify_pptx_only_conversion", convert)
    decisions = lite.optimize_workspace(tmp_path, [item])
    assert decisions[0]["decision"] == "REPLACE_WITH_VERIFIED_PDF"
    assert item.source_copy_path == "sources/deck.pdf"
    assert not (tmp_path / "sources/deck.pptx").exists()


def test_pptx_only_failed_conversion_keeps_original(monkeypatch, tmp_path):
    (tmp_path / "sources").mkdir(); (tmp_path / "documents").mkdir(); (tmp_path / "meta").mkdir()
    (tmp_path / "sources/deck.pptx").write_bytes(b"A" * 100)
    (tmp_path / "documents/deck.md").write_text("unique deck", encoding="utf-8")
    item = record("deck", "sources/deck.pptx", "documents/deck.md")
    monkeypatch.setattr(lite, "verify_pptx_only_conversion", lambda *_: lite.EquivalenceResult(reason="RuntimeError"))
    assert lite.optimize_workspace(tmp_path, [item]) == []
    assert (tmp_path / "sources/deck.pptx").is_file()


def test_related_non_equivalent_pdf_does_not_block_independent_pptx_conversion(monkeypatch, tmp_path):
    (tmp_path / "sources").mkdir(); (tmp_path / "documents").mkdir(); (tmp_path / "meta").mkdir()
    (tmp_path / "sources/deck.pptx").write_bytes(os.urandom(2 * 1024 * 1024))
    (tmp_path / "sources/related.pdf").write_bytes(b"pdf")
    for name in ("deck.md", "related.md"):
        (tmp_path / "documents" / name).write_text("same candidate content " * 30, encoding="utf-8")
    left, right = record("deck", "sources/deck.pptx", "documents/deck.md"), record("related", "sources/related.pdf", "documents/related.md")
    monkeypatch.setattr(lite, "verify_pptx_pdf", lambda *_: lite.EquivalenceResult("NOT_EQUIVALENT", reason="changed"))
    def convert(_source, destination):
        destination.write_bytes(b"converted")
        return lite.EquivalenceResult("FULL_EQUIVALENCE", 4, 4, 4, 1, 2, "verified")
    monkeypatch.setattr(lite, "verify_pptx_only_conversion", convert)
    decisions = lite.optimize_workspace(tmp_path, [left, right])
    assert any(item["decision"] == "REPLACE_WITH_VERIFIED_PDF" for item in decisions)
    assert left.source_copy_path == "sources/deck.pdf"
    assert (tmp_path / "sources/related.pdf").is_file()


def test_pdf_visual_analysis_fails_closed_for_missing_file(tmp_path):
    result = lite.analyze_pdf_visual(tmp_path / "missing.pdf")
    assert result["verdict"] == "UNCERTAIN"


def test_existing_phase_one_decisions_survive_conservative_phase_two(tmp_path):
    (tmp_path / "sources").mkdir(); (tmp_path / "documents").mkdir(); (tmp_path / "meta").mkdir()
    (tmp_path / "meta/lite_retention.json").write_text(json.dumps({"sources":[{"source_id":"old","decision":"OMIT_VERIFIED_DUPLICATE","represented_by":"kept"}]}),encoding="utf-8")
    assert lite.optimize_workspace(tmp_path, []) == [{"source_id":"old","decision":"OMIT_VERIFIED_DUPLICATE","represented_by":"kept"}]
