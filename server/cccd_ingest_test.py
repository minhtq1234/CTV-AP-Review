from pathlib import Path

import pytest

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
