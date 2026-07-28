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
    ocr_side: str = "front",
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
        side=ocr_side,
        side_confidence=.99,
        cccd=cccd,
        cccd_confidence=cccd_conf,
        name=name,
        name_confidence=name_conf,
        number_bbox={"x": 1, "y": 1, "width": 10, "height": 10}
        if has_region else None,
    )
    return CardCandidate(candidate_id, AnalyzedDrawing(drawing, ocr), None, issues)


def test_exact_high_confidence_unique_cccd_resolves():
    result = resolve_candidates(
        [candidate("c1", cccd="000000000001", cccd_conf=.92)],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "exact"
    assert result.resolutions[0].roster_key == "roster-0"
    assert result.resolutions[0].matched_by == "cccd"


@pytest.mark.parametrize(
    ("cccd", "confidence"),
    [
        ("000000000002", .99),
        ("123456789", .99),
        ("000000000001", .84),
    ],
)
def test_fuzzy_cmnd_and_low_confidence_never_resolve_exact(cccd, confidence):
    result = resolve_candidates(
        [candidate("c1", cccd=cccd, cccd_conf=confidence)],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state != "exact"


def test_name_only_is_a_suggestion_not_an_exact_match():
    result = resolve_candidates(
        [candidate("c1", name="Synthetic A", name_conf=.9, has_region=False)],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "suggested"
    assert result.resolutions[0].matched_by == "name"


def test_duplicate_roster_cccd_is_a_conflict():
    result = resolve_candidates(
        [candidate("c1", cccd="000000000001", cccd_conf=.99)],
        [
            {"name": "Synthetic A", "cccd": "000000000001"},
            {"name": "Synthetic B", "cccd": "000000000001"},
        ],
    )

    assert result.resolutions[0].state == "conflict"
    assert "duplicate-cccd" in result.resolutions[0].issues


def test_competing_candidates_are_both_conflicts():
    result = resolve_candidates(
        [
            candidate("c1", cccd="000000000001", cccd_conf=.99),
            candidate("c2", cccd="000000000001", cccd_conf=.99),
        ],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert [resolution.state for resolution in result.resolutions] == [
        "conflict",
        "conflict",
    ]
    assert all(
        "competing-candidate" in resolution.issues
        for resolution in result.resolutions
    )


def test_ambiguous_pair_blocks_exact_match():
    result = resolve_candidates(
        [candidate(
            "c1",
            cccd="000000000001",
            cccd_conf=.99,
            issues=("ambiguous-pair",),
        )],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "conflict"


def test_layout_front_with_unknown_ocr_side_can_resolve_exact():
    result = resolve_candidates(
        [candidate(
            "c1",
            cccd="000000000001",
            cccd_conf=.95,
            ocr_side="unknown",
        )],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "exact"
    assert result.resolutions[0].matched_by == "cccd"


def test_layout_side_conflict_blocks_exact_match():
    result = resolve_candidates(
        [candidate(
            "c1",
            cccd="000000000001",
            cccd_conf=.99,
            issues=("layout-side-conflict",),
        )],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "conflict"
    assert "layout-side-conflict" in result.resolutions[0].issues


def test_blocked_layout_candidate_does_not_claim_valid_target():
    result = resolve_candidates(
        [
            candidate(
                "blocked",
                cccd="000000000001",
                cccd_conf=.99,
                issues=("layout-side-conflict",),
            ),
            candidate(
                "valid",
                cccd="000000000001",
                cccd_conf=.99,
            ),
        ],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    by_id = {
        resolution.candidate_id: resolution
        for resolution in result.resolutions
    }
    assert by_id["blocked"].state == "conflict"
    assert by_id["valid"].state == "exact"
