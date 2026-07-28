import json
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
):
    path = root / "cccd-assets" / "extracted" / f"{drawing_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-image")
    return AnalyzedDrawing(
        EmbeddedDrawing(
            id=drawing_id,
            anchor=Anchor("Sheet1", 1, 1, 5, 5),
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
        ),
        analyzed(root, "drawing-0002", "back"),
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
        lambda drawing: analyzed_by_id[drawing.id],
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
