import json
from dataclasses import replace
from pathlib import Path

import pytest

import cccd_ingest
from cccd_ingest import (
    attach_planned_mapping,
    ingest_cccd_workbook,
    plan_candidate_mappings,
)
from cccd_matching import CardResolution, ResolutionResult
from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, CardCandidate
from cccd_workbook import (
    Anchor,
    EmbeddedDrawing,
    ExtractionResult,
)


CARD_ID = "card-drawing-0001-drawing-0002"
CCCD = "000000000001"


def analyzed(
    root: Path,
    drawing_id: str,
    side: str,
    *,
    cccd: str = "",
    confidence: float = 0.0,
    upright: bool = False,
    anchor: Anchor | None = None,
):
    path = root / "cccd-assets" / "extracted" / f"{drawing_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-image")
    evidence_path = None
    if upright:
        evidence = path.with_name(f"{drawing_id}-upright.png")
        evidence.write_bytes(b"synthetic-upright-image")
        evidence_path = str(evidence)
    return AnalyzedDrawing(
        EmbeddedDrawing(
            id=drawing_id,
            anchor=anchor or Anchor("Sheet1", 1, 1, 5, 5),
            media_type="image/png",
            extension="png",
            width=1000,
            height=630,
            sha256=f"sha-{drawing_id}",
            stored_path=str(path),
        ),
        CccdImageOcr(
            side=side,
            side_confidence=.99,
            cccd=cccd,
            cccd_confidence=confidence,
            name="Synthetic A",
            name_confidence=.9,
            number_bbox={"x": 20, "y": 30, "width": 200, "height": 40}
            if side == "front" else None,
            evidence_path=evidence_path,
            evidence_width=630 if upright else None,
            evidence_height=1000 if upright else None,
        ),
    )


def card(root: Path) -> CardCandidate:
    return CardCandidate(
        CARD_ID,
        analyzed(
            root,
            "drawing-0001",
            "front",
            cccd=CCCD,
            confidence=.95,
            anchor=Anchor("Sheet1", 1, 1, 5, 3),
        ),
        analyzed(
            root,
            "drawing-0002",
            "back",
            anchor=Anchor("Sheet1", 1, 4, 5, 6),
        ),
        (),
    )


def resolution(candidate: CardCandidate) -> ResolutionResult:
    return ResolutionResult(
        expected_mappable_identities=1,
        resolutions=[CardResolution(
            candidate_id=candidate.id,
            state="exact",
            roster_key="roster-0",
            matched_by="cccd",
            issues=(),
        )],
    )


def packet(index: int = 0) -> dict:
    return {
        "index": index,
        "rosterIdentity": {"cccd": CCCD, "name": "Synthetic A"},
        "matchedBy": "cccd",
        "review": {
            "done": False,
            "fields": {},
            "rejection": None,
        },
    }


def exact_plan(root: Path):
    candidate = card(root)
    return plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(root),
    )[0]


def test_mapping_provenance_serializes_full_anchor_offsets(tmp_path):
    candidate = card(tmp_path)
    front = replace(
        candidate.front,
        drawing=replace(
            candidate.front.drawing,
            anchor=Anchor(
                "Sheet1",
                1,
                2,
                5,
                6,
                from_row_offset=10,
                from_col_offset=20,
                to_row_offset=30,
                to_col_offset=40,
            ),
        ),
    )
    candidate = replace(candidate, front=front)

    planned = plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
    )[0]

    assert planned.mapping["front"]["anchor"] == {
        "sheet": "Sheet1",
        "fromRow": 1,
        "fromCol": 2,
        "toRow": 5,
        "toCol": 6,
        "fromRowOffset": 10,
        "fromColOffset": 20,
        "toRowOffset": 30,
        "toColOffset": 40,
    }


def write_manifest(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": "synthetic-packet",
        "name": "Synthetic A",
        "product": "",
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "unrelated": {"preserved": True},
        "docs": [{
            "id": "contract",
            "kind": "contract",
            "label": "Hợp đồng dịch vụ",
            "pages": [{
                "src": "page-0.png",
                "width": 1000,
                "height": 1400,
            }],
        }],
        "fields": [{
            "key": "cccd",
            "label": "Số CCCD",
            "group": "Danh tính",
            "check": "compare",
            "kind": "text",
            "expected": CCCD,
            "sources": [{
                "docId": "contract",
                "page": 0,
                "value": "",
                "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                "confidence": 0.0,
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")


def test_planning_requires_one_exact_packet_target(tmp_path):
    candidate = card(tmp_path)

    unique = plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet(4)],
        str(tmp_path),
    )[0]
    duplicate = plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet(4), packet(5)],
        str(tmp_path),
    )[0]

    assert unique.target_packet_index == 4
    assert duplicate.target_packet_index is None
    assert "non-unique-packet-target" in duplicate.mapping["issues"]


def test_attachment_adds_v1_docs_and_field_source_idempotently(tmp_path):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    planned = exact_plan(tmp_path)

    first = attach_planned_mapping(
        planned,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )
    second = attach_planned_mapping(
        planned,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    owned = [
        document
        for document in manifest["docs"]
        if document["id"].startswith("cccd-excel-")
    ]
    cccd_field = next(
        field for field in manifest["fields"] if field["key"] == "cccd"
    )

    assert [document["kind"] for document in owned] == [
        "id_front",
        "id_back",
    ]
    assert [document["label"] for document in owned] == [
        "CCCD (Excel) · Mặt trước",
        "CCCD (Excel) · Mặt sau",
    ]
    assert [source["docId"] for source in cccd_field["sources"]] == [
        "contract",
        owned[0]["id"],
    ]
    assert cccd_field["sources"][-1]["bbox"] == {
        "x": 20,
        "y": 30,
        "width": 200,
        "height": 40,
    }
    assert first["attachedPacketIndex"] == second["attachedPacketIndex"] == 0
    assert manifest["unrelated"] == {"preserved": True}
    assert "checks" not in manifest


def test_attachment_uses_the_upright_image_that_produced_the_bbox(tmp_path):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    candidate = CardCandidate(
        CARD_ID,
        analyzed(
            tmp_path,
            "drawing-0001",
            "front",
            cccd=CCCD,
            confidence=.95,
            upright=True,
        ),
        analyzed(tmp_path, "drawing-0002", "back"),
        (),
    )
    planned = plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
    )[0]

    result = attach_planned_mapping(
        planned,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    front_doc = next(
        document for document in manifest["docs"]
        if document["kind"] == "id_front"
    )
    front_page = front_doc["pages"][0]
    assert result["attachedPacketIndex"] == 0
    assert front_page["src"].endswith("-upright-front.png")
    assert (front_page["width"], front_page["height"]) == (630, 1000)
    assert next(
        field for field in manifest["fields"] if field["key"] == "cccd"
    )["sources"][-1]["bbox"] == {
        "x": 20,
        "y": 30,
        "width": 200,
        "height": 40,
    }


@pytest.mark.parametrize(
    "bad_packet",
    [None, {}, {"index": "0"}, {"index": 1}],
)
def test_packet_mismatch_preserves_manifest(tmp_path, bad_packet):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()

    result = attach_planned_mapping(
        exact_plan(tmp_path),
        bad_packet,
        str(manifest_path),
        str(tmp_path),
    )

    assert result["attachedPacketIndex"] is None
    assert "attachment-failed" in result["issues"]
    assert manifest_path.read_bytes() == before


def test_manifest_write_failure_rolls_back_new_files(tmp_path, monkeypatch):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()
    monkeypatch.setattr(
        cccd_ingest,
        "_atomic_json_write",
        lambda *args: (_ for _ in ()).throw(OSError("private-write")),
    )

    result = attach_planned_mapping(
        exact_plan(tmp_path),
        packet(),
        str(manifest_path),
        str(tmp_path),
    )

    assert result["attachedPacketIndex"] is None
    assert "attachment-failed" in result["issues"]
    assert manifest_path.read_bytes() == before
    assert not list(manifest_path.parent.glob("cccd-*.png"))


def test_ingest_returns_aggregate_and_preserves_unresolved_provenance(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    candidate = card(tmp_path)
    drawings = [candidate.front.drawing, candidate.back.drawing]
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(2, drawings, []),
    )
    analyzed_by_id = {
        candidate.front.drawing.id: candidate.front.ocr,
        candidate.back.drawing.id: candidate.back.ocr,
    }
    monkeypatch.setattr(
        cccd_ingest,
        "analyze_drawing",
        lambda drawing, *args: analyzed_by_id[drawing.id],
    )

    result = ingest_cccd_workbook(
        str(tmp_path / "cards.xlsx"),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    assert result["cccdWorkbook"]["status"] == "ready"
    assert result["cccdWorkbook"]["summary"] == {
        "candidates": 1,
        "attached": 1,
        "unresolved": 0,
    }
    mapping = result["cccdWorkbook"]["mappings"][0]
    assert mapping["candidateId"] == CARD_ID
    assert mapping["attachedPacketIndex"] == 0
    assert mapping["front"]["sourcePath"].startswith("cccd-assets/")


def test_ingest_removes_prior_attachment_when_match_becomes_unresolved(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    first_candidate = card(tmp_path)
    attached = attach_planned_mapping(
        exact_plan(tmp_path),
        packet(),
        str(manifest_path),
        str(tmp_path),
    )
    assert attached["attachedPacketIndex"] == 0
    weak_front = replace(
        first_candidate.front.ocr,
        cccd_confidence=.40,
    )
    analyzed_by_id = {
        first_candidate.front.drawing.id: weak_front,
        first_candidate.back.drawing.id: first_candidate.back.ocr,
    }
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(
            2,
            [first_candidate.front.drawing, first_candidate.back.drawing],
            [],
        ),
    )
    monkeypatch.setattr(
        cccd_ingest,
        "analyze_drawing",
        lambda drawing, *args: analyzed_by_id[drawing.id],
    )

    result = ingest_cccd_workbook(
        str(tmp_path / "cards.xlsx"),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cccd_field = next(
        field for field in manifest["fields"] if field["key"] == "cccd"
    )
    assert result["cccdWorkbook"]["summary"]["attached"] == 0
    assert not [
        document for document in manifest["docs"]
        if document["id"].startswith("cccd-excel-")
    ]
    assert [source["docId"] for source in cccd_field["sources"]] == ["contract"]
    assert not list(manifest_path.parent.glob("cccd-*.png"))


def test_unknown_side_mapping_preserves_image_provenance(tmp_path):
    unknown = analyzed(tmp_path, "drawing-unknown", "unknown")
    unknown = replace(
        unknown,
        ocr=replace(
            unknown.ocr,
            cccd=CCCD,
            cccd_confidence=.72,
            number_bbox={"x": 2, "y": 3, "width": 40, "height": 8},
        ),
    )
    candidate = CardCandidate(
        "card-drawing-unknown",
        None,
        None,
        ("unknown-side",),
        unknown,
    )
    planned = plan_candidate_mappings(
        [candidate],
        ResolutionResult(
            expected_mappable_identities=1,
            resolutions=[CardResolution(
                candidate_id=candidate.id,
                state="manual",
                roster_key=None,
                matched_by=None,
                issues=("no-front",),
            )],
        ),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
    )[0]

    assert planned.mapping["front"] is None
    assert planned.mapping["back"] is None
    assert planned.mapping["unknown"]["drawingId"] == "drawing-unknown"
    assert planned.mapping["unknown"]["sourcePath"].startswith("cccd-assets/")
    assert planned.mapping["ocrIdentity"]["cccd"] == CCCD
    assert planned.mapping["ocrConfidence"]["cccd"] == .72
    assert planned.mapping["numberBbox"] == {
        "x": 2,
        "y": 3,
        "width": 40,
        "height": 8,
    }


def test_ingest_removes_prior_attachment_when_candidate_disappears(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    attached = attach_planned_mapping(
        exact_plan(tmp_path),
        packet(),
        str(manifest_path),
        str(tmp_path),
    )
    assert attached["attachedPacketIndex"] == 0
    unknown = analyzed(tmp_path, "drawing-replacement", "unknown")
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(1, [unknown.drawing], []),
    )
    monkeypatch.setattr(
        cccd_ingest,
        "analyze_drawing",
        lambda drawing, *args: unknown.ocr,
    )

    result = ingest_cccd_workbook(
        str(tmp_path / "cards.xlsx"),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping = result["cccdWorkbook"]["mappings"][0]
    assert mapping["candidateId"] == "card-drawing-replacement"
    assert mapping["unknown"]["drawingId"] == "drawing-replacement"
    assert not [
        document for document in manifest["docs"]
        if document["id"].startswith("cccd-excel-")
    ]
    assert not list(manifest_path.parent.glob("cccd-*.png"))


def test_workbook_failure_is_safe_and_keeps_packet_case_usable(
    tmp_path,
    monkeypatch,
):
    packets = [packet()]
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: (_ for _ in ()).throw(ValueError("private-workbook")),
    )

    result = ingest_cccd_workbook(
        "bad.xlsx",
        [{"name": "Synthetic A", "cccd": CCCD}],
        packets,
        str(tmp_path),
        {},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    assert result["packets"] is packets
    assert result["cccdWorkbook"] == {
        "status": "error",
        "errorCode": "invalid-workbook",
        "summary": {"candidates": 0, "attached": 0, "unresolved": 0},
        "mappings": [],
    }


def test_workbook_failure_removes_prior_attached_evidence(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    attached = attach_planned_mapping(
        exact_plan(tmp_path),
        packet(),
        str(manifest_path),
        str(tmp_path),
    )
    assert attached["attachedPacketIndex"] == 0
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: (_ for _ in ()).throw(ValueError("private-workbook")),
    )

    result = ingest_cccd_workbook(
        "bad.xlsx",
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["cccdWorkbook"]["errorCode"] == "invalid-workbook"
    assert not [
        document for document in manifest["docs"]
        if document["id"].startswith("cccd-excel-")
    ]
    assert not list(manifest_path.parent.glob("cccd-*.png"))
