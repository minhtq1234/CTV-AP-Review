import pytest

from cccd_matching import resolve_candidates
from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, CardCandidate
from cccd_workbook import Anchor, EmbeddedDrawing


def candidate(
    candidate_id: str,
    *,
    cccd: str = "",
    cccd_conf: float = 0.0,
    name: str = "",
    name_conf: float = 0.0,
    has_front: bool = True,
    has_region: bool = True,
    issues: tuple[str, ...] = (),
) -> CardCandidate:
    if not has_front:
        return CardCandidate(candidate_id, None, None, issues)
    drawing = EmbeddedDrawing(
        id=f"drawing-{candidate_id}",
        anchor=Anchor("Synthetic", 0, 0, 1, 1),
        media_type="image/png",
        extension="png",
        width=100,
        height=100,
        sha256="0" * 64,
        stored_path=f"/synthetic/{candidate_id}.png",
    )
    ocr = CccdImageOcr(
        side="front",
        side_confidence=.99,
        cccd=cccd,
        cccd_confidence=cccd_conf,
        name=name,
        name_confidence=name_conf,
        number_bbox={"x": 1, "y": 1, "width": 10, "height": 10} if has_region else None,
    )
    return CardCandidate(candidate_id, AnalyzedDrawing(drawing, ocr), None, issues)


def test_high_confidence_exact_12_digit_unique_match_is_exact():
    card = candidate("c1", cccd="079123456789", cccd_conf=.92, name="Alpha", name_conf=.9)
    rows = [{"name": "Alpha", "cccd": "079123456789"}]

    result = resolve_candidates([card], rows)

    assert result.expected_mappable_identities == 1
    assert result.resolutions[0].state == "exact"
    assert result.resolutions[0].roster_key == "roster-0"
    assert result.resolutions[0].matched_by == "cccd"


@pytest.mark.parametrize("cccd, confidence", [
    ("079123456788", .99),  # fuzzy by one digit: still manual
    ("123456789", .99),     # CMND: manual
    ("079123456789", .84),  # below threshold: manual/suggested
])
def test_non_exact_or_low_confidence_never_auto_matches(cccd, confidence):
    card = candidate("c1", cccd=cccd, cccd_conf=confidence, name="", name_conf=0)
    rows = [{"name": "Alpha", "cccd": "079123456789"}]

    assert resolve_candidates([card], rows).resolutions[0].state != "exact"


def test_threshold_confidence_is_inclusive_for_an_exact_match():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.85)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    assert result.resolutions[0].state == "exact"


def test_unique_high_confidence_name_is_suggested_not_exact():
    result = resolve_candidates(
        [candidate("c1", name="Alpha", name_conf=.8)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    resolution = result.resolutions[0]
    assert resolution.state == "suggested"
    assert resolution.roster_key == "roster-0"
    assert resolution.matched_by == "name"


def test_duplicate_roster_cccd_is_a_conflict_not_an_exact_match():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.99)],
        [
            {"name": "Alpha", "cccd": "079123456789"},
            {"name": "Bravo", "cccd": "079123456789"},
        ],
    )

    assert result.resolutions[0].state == "conflict"
    assert "duplicate-cccd" in result.resolutions[0].issues


def test_duplicate_roster_name_blocks_an_otherwise_exact_cccd_match():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.99, name="Alpha", name_conf=.9)],
        [
            {"name": "Alpha", "cccd": "079123456789"},
            {"name": "Alpha", "cccd": "079123456788"},
        ],
    )

    assert result.resolutions[0].state == "conflict"
    assert "duplicate-name" in result.resolutions[0].issues


def test_conflicting_unique_cccd_and_name_evidence_is_a_conflict():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.99, name="Bravo", name_conf=.9)],
        [
            {"name": "Alpha", "cccd": "079123456789"},
            {"name": "Bravo", "cccd": "079123456788"},
        ],
    )

    assert result.resolutions[0].state == "conflict"
    assert "conflicting-identity" in result.resolutions[0].issues


def test_candidate_without_a_front_is_manual():
    result = resolve_candidates(
        [candidate("c1", has_front=False)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    assert result.resolutions[0].state == "manual"
    assert "no-front" in result.resolutions[0].issues


def test_candidate_without_a_located_number_region_is_manual():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.99, has_region=False)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    assert result.resolutions[0].state == "manual"
    assert "no-number-region" in result.resolutions[0].issues


def test_unique_name_without_a_number_region_can_only_be_suggested():
    result = resolve_candidates(
        [candidate("c1", name="Alpha", name_conf=.9, has_region=False)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    resolution = result.resolutions[0]
    assert resolution.state == "suggested"
    assert resolution.matched_by == "name"


def test_multiple_candidates_targeting_one_identity_are_conflicts():
    cards = [
        candidate("c1", cccd="079123456789", cccd_conf=.99),
        candidate("c2", cccd="079123456789", cccd_conf=.99),
    ]
    result = resolve_candidates(cards, [{"name": "Alpha", "cccd": "079123456789"}])

    assert [resolution.state for resolution in result.resolutions] == ["conflict", "conflict"]
    assert all("competing-candidate" in resolution.issues for resolution in result.resolutions)


def test_duplicate_candidate_ids_are_rejected_before_any_can_be_exact():
    cards = [
        candidate("duplicate", cccd="079123456789", cccd_conf=.99),
        candidate("duplicate", cccd="079123456789", cccd_conf=.99),
    ]

    with pytest.raises(ValueError, match="duplicate candidate id"):
        resolve_candidates(cards, [{"name": "Alpha", "cccd": "079123456789"}])


def test_unreadable_candidate_stays_manual():
    result = resolve_candidates(
        [candidate("c1", cccd="not-a-number", cccd_conf=.99, name="", name_conf=0)],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    assert result.resolutions[0].state == "manual"
    assert "unreadable-identity" in result.resolutions[0].issues


def test_pairing_ambiguity_blocks_an_otherwise_exact_match():
    result = resolve_candidates(
        [candidate("c1", cccd="079123456789", cccd_conf=.99, issues=("ambiguous-pair",))],
        [{"name": "Alpha", "cccd": "079123456789"}],
    )

    assert result.resolutions[0].state == "conflict"
    assert "ambiguous-pair" in result.resolutions[0].issues


def test_denominator_counts_unique_eligible_roster_identities_without_candidates():
    result = resolve_candidates([], [
        {"name": "Alpha", "cccd": "079123456789"},
        {"name": "Bravo", "cccd": "079123456788"},
        {"name": "Duplicate", "cccd": "079123456789"},
        {"name": "Legacy", "cccd": "123456789"},
    ])

    assert result.expected_mappable_identities == 2


def test_zero_eligible_roster_identities_is_invalid():
    with pytest.raises(ValueError, match="eligible roster identity"):
        resolve_candidates([], [{"name": "Legacy", "cccd": "123456789"}])
