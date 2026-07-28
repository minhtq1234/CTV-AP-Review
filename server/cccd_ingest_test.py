import hashlib
import json
from pathlib import Path

import pytest

import cccd_ingest
from cccd_ingest import plan_candidate_mappings
from cccd_matching import CardResolution, ResolutionResult
from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, CardCandidate
from cccd_workbook import Anchor, EmbeddedDrawing


CARD_ID = "card-drawing-0001-drawing-0002"
CCCD = "000000000001"


def analyzed(
    root: Path,
    drawing_id: str,
    side: str,
    *,
    cccd: str = "",
    confidence: float = 0.0,
    stored_path: Path | None = None,
):
    path = stored_path or root / "cccd-assets" / "extracted" / f"{drawing_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-image")
    drawing = EmbeddedDrawing(
        id=drawing_id,
        anchor=Anchor("Sheet1", 1, 1, 5, 5),
        media_type="image/png",
        extension="png",
        width=1000,
        height=630,
        sha256=f"sha-{drawing_id}",
        stored_path=str(path),
    )
    return AnalyzedDrawing(
        drawing,
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


def candidate(
    root: Path,
    *,
    candidate_id: str = CARD_ID,
    front: AnalyzedDrawing | None = None,
    back: AnalyzedDrawing | None = None,
    issues: tuple[str, ...] = (),
) -> CardCandidate:
    return CardCandidate(
        id=candidate_id,
        front=front if front is not None else analyzed(root, "drawing-0001", "front", cccd=CCCD, confidence=.95),
        back=back if back is not None else analyzed(root, "drawing-0002", "back"),
        issues=issues,
    )


def resolution(
    card: CardCandidate,
    *,
    state: str = "exact",
    roster_key: str | None = "roster-0",
    issues: tuple[str, ...] = (),
) -> ResolutionResult:
    return ResolutionResult(
        expected_mappable_identities=1,
        resolutions=[CardResolution(
            candidate_id=card.id,
            state=state,
            roster_key=roster_key,
            matched_by="cccd" if state == "exact" else "name",
            issues=issues,
        )],
    )


def packet(index: int = 0, cccd: str = CCCD) -> dict:
    return {
        "index": index,
        "rosterIdentity": {"cccd": cccd, "name": "Synthetic A"},
        "matchedBy": "cccd",
    }


def roster(cccd: str = CCCD) -> list[dict[str, str]]:
    return [{"name": "Synthetic A", "cccd": cccd}]


def plan(root: Path, card: CardCandidate, result: ResolutionResult, *, rows=None, packets=None):
    return plan_candidate_mappings(
        [card], result, roster() if rows is None else rows, [packet()] if packets is None else packets, str(root),
    )[0]


def write_manifest(path: Path, *, fields=None, docs=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": "synthetic-packet",
        "name": "Synthetic A",
        "product": "",
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "unrelated": {"preserved": True},
        "docs": docs if docs is not None else [{
            "id": "contract",
            "kind": "contract",
            "label": "Hợp đồng dịch vụ",
            "pages": [{"src": "page-0.png", "width": 1000, "height": 1400}],
        }],
        "fields": fields if fields is not None else [{
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


def exact_plan(root: Path, *, card: CardCandidate | None = None):
    card = card or candidate(root)
    return plan(root, card, resolution(card))


def test_attach_adds_front_back_a1_and_is_idempotent(tmp_path):
    from cccd_ingest import attach_planned_mapping

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    planned = exact_plan(tmp_path)

    first = attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))
    second = attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    owned = [doc for doc in manifest["docs"] if doc["id"].startswith("cccd-excel-")]
    candidate_token = hashlib.sha256(CARD_ID.encode("utf-8")).hexdigest()[:12]
    assert [doc["kind"] for doc in owned] == ["id_front", "id_back"]
    assert [doc["label"] for doc in owned] == [
        "CCCD (Excel) · Mặt trước", "CCCD (Excel) · Mặt sau",
    ]
    assert [doc["pages"][0]["src"].rsplit("/", 1)[-1] for doc in owned] == [
        f"cccd-{candidate_token}-sha-drawing--front.png",
        f"cccd-{candidate_token}-sha-drawing--back.png",
    ]
    assert manifest["docs"][0]["id"] == "contract"
    cccd_field = next(field for field in manifest["fields"] if field["key"] == "cccd")
    assert [source["docId"] for source in cccd_field["sources"]] == ["contract", owned[0]["id"]]
    a1 = next(check for check in manifest["checks"] if check["code"] == "A1")
    assert a1["evidenceDocId"] == owned[0]["id"]
    assert a1["source"]["bbox"] == {"x": 20, "y": 30, "width": 200, "height": 40}
    assert a1["autostatus"] == "review"
    assert first["attachedPacketIndex"] == second["attachedPacketIndex"] == 0
    assert first["front"]["packetPath"] == second["front"]["packetPath"]
    assert first["front"]["packetPath"] == owned[0]["pages"][0]["src"].removeprefix(f"{tmp_path}/")
    assert manifest["unrelated"] == {"preserved": True}


def test_non_target_plan_never_mutates_manifest(tmp_path):
    from cccd_ingest import attach_planned_mapping

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()
    card = candidate(tmp_path)
    planned = plan(tmp_path, card, resolution(card), packets=[])

    result = attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))

    assert result == planned.mapping
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("bad_packet", [None, {}, {"index": "0"}, {"index": 1}])
def test_attachment_packet_mismatch_is_safe_and_keeps_manifest(tmp_path, bad_packet):
    from cccd_ingest import attach_planned_mapping

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()

    result = attach_planned_mapping(exact_plan(tmp_path), bad_packet, str(manifest_path), str(tmp_path))

    assert result["attachedPacketIndex"] is None
    assert result["issues"].count("attachment-failed") == 1
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("failure", ["missing-field", "missing-bbox", "copy", "checklist", "write"])
def test_attachment_failures_rollback_manifest_and_new_files(tmp_path, monkeypatch, failure):
    import cccd_ingest as ingest

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    if failure == "missing-field":
        write_manifest(manifest_path, fields=[])
        planned = exact_plan(tmp_path)
    elif failure == "missing-bbox":
        front = analyzed(tmp_path, "drawing-0001", "front", cccd=CCCD, confidence=.95)
        card = candidate(tmp_path, front=AnalyzedDrawing(
            front.drawing,
            CccdImageOcr("front", .99, CCCD, .95, "Synthetic A", .9, None),
        ))
        write_manifest(manifest_path)
        planned = exact_plan(tmp_path, card=card)
    else:
        write_manifest(manifest_path)
        planned = exact_plan(tmp_path)
    before = manifest_path.read_bytes()
    if failure == "copy":
        monkeypatch.setattr(ingest.shutil, "copyfile", lambda *args: (_ for _ in ()).throw(OSError("private-copy")))
    elif failure == "checklist":
        monkeypatch.setattr(ingest.checklist, "build_checklist", lambda *args: (_ for _ in ()).throw(ValueError("private-checklist")))
    elif failure == "write":
        monkeypatch.setattr(ingest, "_atomic_json_write", lambda *args: (_ for _ in ()).throw(OSError("private-write")))

    result = ingest.attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))

    assert result["attachedPacketIndex"] is None
    assert result["issues"].count("attachment-failed") == 1
    assert manifest_path.read_bytes() == before
    assert not list(manifest_path.parent.glob("cccd-*.png"))


def test_stale_owned_files_are_replaced_only_after_successful_manifest_commit(tmp_path, monkeypatch):
    import cccd_ingest as ingest

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    stale = manifest_path.parent / "cccd-old-front.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    write_manifest(manifest_path, docs=[{
        "id": f"cccd-excel-{CARD_ID}-front", "kind": "id_front", "label": "old",
        "pages": [{"src": str(stale), "width": 1, "height": 1}],
    }])
    planned = exact_plan(tmp_path)
    monkeypatch.setattr(ingest, "_atomic_json_write", lambda *args: (_ for _ in ()).throw(OSError("no commit")))

    failed = ingest.attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))

    assert failed["attachedPacketIndex"] is None
    assert stale.exists()
    monkeypatch.undo()
    attached = ingest.attach_planned_mapping(planned, packet(), str(manifest_path), str(tmp_path))
    assert attached["attachedPacketIndex"] == 0
    assert not stale.exists()


def test_stale_file_cleanup_error_does_not_hide_committed_attachment(tmp_path, monkeypatch):
    import cccd_ingest as ingest

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    stale = manifest_path.parent / "cccd-old-front.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    write_manifest(manifest_path, docs=[{
        "id": f"cccd-excel-{CARD_ID}-front", "kind": "id_front", "label": "old",
        "pages": [{"src": str(stale), "width": 1, "height": 1}],
    }])
    real_unlink = ingest.os.unlink

    def refuse_stale(path):
        if path == str(stale):
            raise OSError("cleanup failed")
        return real_unlink(path)

    monkeypatch.setattr(ingest.os, "unlink", refuse_stale)

    result = ingest.attach_planned_mapping(exact_plan(tmp_path), packet(), str(manifest_path), str(tmp_path))

    assert result["attachedPacketIndex"] == 0
    assert "attachment-failed" not in result["issues"]
    assert any(doc["id"].startswith("cccd-excel-") for doc in json.loads(manifest_path.read_text())["docs"])


def install_extraction(monkeypatch, card: CardCandidate, *, issues=(), drawing_instances=2):
    from cccd_workbook import ExtractionResult

    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *_args: ExtractionResult(
            drawing_instances,
            [card.front.drawing, card.back.drawing],
            list(issues),
        ),
    )


def install_ocr(monkeypatch, card: CardCandidate):
    by_id = {card.front.drawing.id: card.front.ocr, card.back.drawing.id: card.back.ocr}
    monkeypatch.setattr(cccd_ingest, "analyze_drawing", lambda drawing: by_id[drawing.id])


def test_ingest_returns_ready_counts_durable_mapping_and_progress(tmp_path, monkeypatch):
    card = candidate(tmp_path)
    install_extraction(monkeypatch, card)
    install_ocr(monkeypatch, card)
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    progress = []

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"), lambda *args: progress.append(args),
    )

    workbook = result["cccdWorkbook"]
    assert result["packets"] == [packet()]
    assert workbook["status"] == "ready"
    assert workbook["summary"] == {"candidates": 1, "attached": 1, "unresolved": 0}
    assert workbook["mappings"][0]["attachedPacketIndex"] == 0
    assert progress == [("cccd", 1, 1, "")]


def test_ingest_marks_extraction_issue_partial(tmp_path, monkeypatch):
    from cccd_workbook import ExtractionIssue

    card = candidate(tmp_path)
    install_extraction(monkeypatch, card, issues=[ExtractionIssue("unsupported-media", "drawing-0003")], drawing_instances=3)
    install_ocr(monkeypatch, card)
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"), lambda *_args: None,
    )

    assert result["cccdWorkbook"]["status"] == "partial"
    assert result["cccdWorkbook"]["errorCode"] == "extraction-incomplete"


def test_ingest_workbook_failure_is_safe_and_keeps_packets(tmp_path, monkeypatch):
    from cccd_workbook import CccdWorkbookError

    monkeypatch.setattr(
        cccd_ingest, "extract_drawings",
        lambda *_args: (_ for _ in ()).throw(CccdWorkbookError("private-detail")),
    )
    packets = [packet()]

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", [], packets, str(tmp_path), {}, str(tmp_path / "cccd-assets"),
        lambda *_args: None,
    )

    assert result["packets"] == packets
    assert result["cccdWorkbook"] == {
        "status": "error", "errorCode": "invalid-workbook",
        "summary": {"candidates": 0, "attached": 0, "unresolved": 0}, "mappings": [],
    }
    assert "private-detail" not in json.dumps(result)


def test_ingest_without_supported_images_is_safe_error(tmp_path, monkeypatch):
    from cccd_workbook import ExtractionResult

    monkeypatch.setattr(cccd_ingest, "extract_drawings", lambda *_args: ExtractionResult(2, [], []))

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {}, str(tmp_path / "cccd-assets"),
        lambda *_args: None,
    )

    assert result["cccdWorkbook"] == {
        "status": "error", "errorCode": "no-supported-images",
        "summary": {"candidates": 0, "attached": 0, "unresolved": 0}, "mappings": [],
    }


def test_ingest_without_usable_ocr_is_safe_error(tmp_path, monkeypatch):
    card = candidate(tmp_path)
    install_extraction(monkeypatch, card)
    monkeypatch.setattr(
        cccd_ingest, "analyze_drawing",
        lambda _drawing: (_ for _ in ()).throw(RuntimeError("private-ocr-detail")),
    )

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {}, str(tmp_path / "cccd-assets"),
        lambda *_args: None,
    )

    assert result["cccdWorkbook"]["status"] == "error"
    assert result["cccdWorkbook"]["errorCode"] == "ocr-unavailable"
    assert "private-ocr-detail" not in json.dumps(result)


def test_ingest_with_one_ocr_failure_is_partial_without_private_detail(tmp_path, monkeypatch):
    card = candidate(tmp_path)
    install_extraction(monkeypatch, card)

    def analyze(drawing):
        if drawing.id == card.back.drawing.id:
            raise RuntimeError("private-back-ocr-detail")
        return card.front.ocr

    monkeypatch.setattr(cccd_ingest, "analyze_drawing", analyze)
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"), lambda *_args: None,
    )

    assert result["cccdWorkbook"]["status"] == "partial"
    assert result["cccdWorkbook"]["errorCode"] == "ocr-unavailable"
    assert result["cccdWorkbook"]["summary"]["candidates"] == 1
    assert "private-back-ocr-detail" not in json.dumps(result)


def test_ingest_attachment_failure_is_partial_and_unresolved(tmp_path, monkeypatch):
    card = candidate(tmp_path)
    install_extraction(monkeypatch, card)
    install_ocr(monkeypatch, card)
    monkeypatch.setattr(
        cccd_ingest, "_atomic_json_write",
        lambda *_args: (_ for _ in ()).throw(OSError("private-write-detail")),
    )
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"), lambda *_args: None,
    )

    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "partial"
    assert workbook["errorCode"] == "attachment-failed"
    assert workbook["summary"] == {"candidates": 1, "attached": 0, "unresolved": 1}
    assert workbook["mappings"][0]["attachedPacketIndex"] is None
    assert "private-write-detail" not in json.dumps(workbook)


def test_manual_unresolved_mapping_is_still_ready(tmp_path, monkeypatch):
    front = analyzed(tmp_path, "drawing-0001", "front", cccd=CCCD, confidence=.4)
    card = candidate(tmp_path, front=front)
    install_extraction(monkeypatch, card)
    install_ocr(monkeypatch, card)

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [packet()], str(tmp_path), {}, str(tmp_path / "cccd-assets"),
        lambda *_args: None,
    )

    assert result["cccdWorkbook"]["status"] == "ready"
    assert result["cccdWorkbook"]["summary"] == {"candidates": 1, "attached": 0, "unresolved": 1}


def test_malformed_packets_and_manifest_map_cannot_crash_or_leak_detail(tmp_path, monkeypatch):
    card = candidate(tmp_path)
    install_extraction(monkeypatch, card)
    install_ocr(monkeypatch, card)

    result = cccd_ingest.ingest_cccd_workbook(
        "cards.xlsx", roster(), [None, {"index": True}, packet()], str(tmp_path),
        {"not-an-index": object(), 0: object()}, str(tmp_path / "cccd-assets"),
        lambda *_args: None,
    )

    assert result["cccdWorkbook"]["status"] == "partial"
    assert result["cccdWorkbook"]["errorCode"] == "attachment-failed"
    assert "object at" not in json.dumps(result)


def test_exact_resolution_targets_one_packet_and_serializes_relative_provenance(tmp_path):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card))

    assert planned.target_packet_index == 0
    assert planned.mapping == {
        "candidateId": CARD_ID,
        "front": {
            "drawingId": "drawing-0001",
            "mediaType": "image/png",
            "width": 1000,
            "height": 630,
            "sha256": "sha-drawing-0001",
            "sourcePath": "cccd-assets/extracted/drawing-0001.png",
            "packetPath": None,
            "anchor": {"sheet": "Sheet1", "fromRow": 1, "fromCol": 1, "toRow": 5, "toCol": 5},
        },
        "back": {
            "drawingId": "drawing-0002",
            "mediaType": "image/png",
            "width": 1000,
            "height": 630,
            "sha256": "sha-drawing-0002",
            "sourcePath": "cccd-assets/extracted/drawing-0002.png",
            "packetPath": None,
            "anchor": {"sheet": "Sheet1", "fromRow": 1, "fromCol": 1, "toRow": 5, "toCol": 5},
        },
        "ocrIdentity": {"cccd": CCCD, "name": "Synthetic A"},
        "ocrConfidence": {"cccd": .95, "name": .9},
        "numberBbox": {"x": 20, "y": 30, "width": 200, "height": 40},
        "state": "exact",
        "attachedPacketIndex": None,
        "matchMethod": "cccd",
        "issues": [],
    }


@pytest.mark.parametrize(("packets", "issue"), [
    ([], "packet-target-not-found"),
    ([packet(0), packet(1)], "non-unique-packet-target"),
])
def test_exact_resolution_with_non_unique_packet_target_does_not_attach(tmp_path, packets, issue):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card), packets=packets)

    assert planned.target_packet_index is None
    assert issue in planned.mapping["issues"]


@pytest.mark.parametrize("malformed_packet", [
    None,
    {"rosterIdentity": {"cccd": CCCD}},
    {"index": "0", "rosterIdentity": {"cccd": CCCD}},
    {"index": True, "rosterIdentity": {"cccd": CCCD}},
    {"index": -1, "rosterIdentity": {"cccd": CCCD}},
    {"index": 0, "rosterIdentity": "not-a-record"},
    {"index": 0, "rosterIdentity": {"cccd": 1}},
])
def test_malformed_packet_entries_are_skipped_without_attaching(tmp_path, malformed_packet):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card), packets=[malformed_packet])

    assert planned.target_packet_index is None
    assert "packet-target-not-found" in planned.mapping["issues"]


def test_malformed_packet_entry_does_not_block_a_valid_target(tmp_path):
    card = candidate(tmp_path)

    planned = plan(
        tmp_path,
        card,
        resolution(card),
        packets=[{"index": True, "rosterIdentity": {"cccd": CCCD}}, packet()],
    )

    assert planned.target_packet_index == 0
    assert "packet-target-not-found" not in planned.mapping["issues"]


@pytest.mark.parametrize("state", ["suggested", "manual", "conflict"])
def test_non_exact_resolution_never_targets_packet(tmp_path, state):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card, state=state, roster_key="roster-0"))

    assert planned.target_packet_index is None
    assert planned.mapping["attachedPacketIndex"] is None


@pytest.mark.parametrize("roster_key", [None, "missing-0", "roster-", "roster-nope", "roster--1", "roster-1"])
def test_invalid_missing_out_of_range_or_negative_roster_key_never_targets(tmp_path, roster_key):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card, roster_key=roster_key))

    assert planned.target_packet_index is None
    assert "invalid-roster-key" in planned.mapping["issues"]


def test_non_12_digit_roster_cccd_never_targets(tmp_path):
    card = candidate(tmp_path)

    planned = plan(tmp_path, card, resolution(card), rows=roster("000-000-001"))

    assert planned.target_packet_index is None
    assert "non-12-digit-roster-cccd" in planned.mapping["issues"]


@pytest.mark.parametrize("candidates, resolutions", [
    (lambda root: [candidate(root)], lambda card: []),
    (lambda root: [], lambda card: [CardResolution(CARD_ID, "exact", "roster-0", "cccd", ())]),
    (lambda root: [candidate(root), candidate(root)], lambda card: [CardResolution(card.id, "exact", "roster-0", "cccd", ())]),
    (lambda root: [candidate(root)], lambda card: [
        CardResolution(card.id, "exact", "roster-0", "cccd", ()),
        CardResolution(card.id, "exact", "roster-0", "cccd", ()),
    ]),
])
def test_candidate_resolution_id_mismatch_or_duplicates_are_rejected(tmp_path, candidates, resolutions):
    cards = candidates(tmp_path)
    card = cards[0] if cards else candidate(tmp_path)
    result = ResolutionResult(expected_mappable_identities=1, resolutions=resolutions(card))

    with pytest.raises(ValueError, match="candidate-resolution-mismatch"):
        plan_candidate_mappings(cards, result, roster(), [packet()], str(tmp_path))


def test_source_asset_outside_case_root_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside.png"
    front = analyzed(tmp_path, "drawing-outside", "front", cccd=CCCD, confidence=.95, stored_path=outside)
    card = candidate(tmp_path, front=front)

    with pytest.raises(ValueError, match="CCCD asset escaped case directory"):
        plan(tmp_path, card, resolution(card))


def test_commonpath_drive_error_is_normalized_to_case_escape(tmp_path, monkeypatch):
    card = candidate(tmp_path)

    def different_drives(_paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(cccd_ingest.os.path, "commonpath", different_drives)

    with pytest.raises(ValueError, match="^CCCD asset escaped case directory$"):
        plan(tmp_path, card, resolution(card))


def test_candidate_and_resolution_issues_are_retained_in_order_without_duplicates(tmp_path):
    card = candidate(tmp_path, issues=("pair-issue", "shared-issue", "pair-issue"))

    planned = plan(
        tmp_path,
        card,
        resolution(card, issues=("shared-issue", "resolution-issue", "resolution-issue")),
        packets=[],
    )

    assert planned.mapping["issues"] == [
        "pair-issue", "shared-issue", "resolution-issue", "packet-target-not-found",
    ]


def test_absent_front_and_back_serializes_safely(tmp_path):
    card = candidate(tmp_path, front=None, back=None)
    card = CardCandidate(card.id, None, None, card.issues)

    planned = plan(tmp_path, card, resolution(card, state="manual", roster_key=None))

    assert planned.mapping["front"] is None
    assert planned.mapping["back"] is None
    assert planned.mapping["ocrIdentity"] == {"cccd": "", "name": ""}
    assert planned.mapping["ocrConfidence"] == {"cccd": 0.0, "name": 0.0}
    assert planned.mapping["numberBbox"] is None


def test_candidates_are_planned_in_candidate_id_order(tmp_path):
    z_card = candidate(tmp_path, candidate_id="card-z")
    a_card = candidate(tmp_path, candidate_id="card-a")
    result = ResolutionResult(
        expected_mappable_identities=1,
        resolutions=[
            CardResolution("card-z", "manual", None, None, ()),
            CardResolution("card-a", "manual", None, None, ()),
        ],
    )

    plans = plan_candidate_mappings([z_card, a_card], result, roster(), [packet()], str(tmp_path))

    assert [planned.candidate.id for planned in plans] == ["card-a", "card-z"]
