import pytest

from boundary_proposal import build_boundary_proposal, validate_revision_starts


def _manifest(*relative_contract_starts: int, boundary_evidence=None) -> dict:
    manifest = {
        "docs": [
            {
                "id": f"contract-{index}",
                "kind": "contract",
                "pages": [{"src": f"/private/pg{page}.png"}],
            }
            for index, page in enumerate(relative_contract_starts)
        ],
    }
    if boundary_evidence is not None:
        manifest["boundaryEvidence"] = boundary_evidence
    return manifest


def test_proposal_fuses_contract_and_cadence_without_forcing_roster_count():
    case = {
        "id": "source-case",
        "summary": {"found": 2, "roster_n": 3},
        "packets": [
            {"index": 0, "pages": [0, 7], "flags": []},
            {"index": 1, "pages": [8, 23], "flags": ["length-out-of-range"]},
        ],
    }
    manifests = {
        0: _manifest(0),
        1: _manifest(0, 8),
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=24)

    assert proposal["status"] == "review_required"
    assert proposal["expectedPacketCount"] == 3
    assert [candidate["page"] for candidate in proposal["candidateStarts"]] == [0, 8, 16]
    assert proposal["candidateStarts"][2] == {
        "page": 16,
        "signals": ["contract-title", "cadence"],
        "confidence": "high",
        "packetIndex": 1,
        "relativePage": 8,
    }


def test_visual_current_start_alone_has_medium_confidence():
    case = {
        "id": "visual-only",
        "packets": [{"index": 4, "pages": [5, 12], "flags": []}],
    }

    proposal = build_boundary_proposal(case, {}, total_pages=13)

    assert proposal["status"] == "not_needed"
    assert proposal["candidateStarts"] == [
        {
            "page": 5,
            "signals": ["visual"],
            "confidence": "medium",
            "packetIndex": 4,
            "relativePage": 0,
        }
    ]


def test_candidates_are_sorted_deduplicated_and_roster_never_creates_start():
    case = {
        "id": "ordered",
        "summary": {"found": 2, "roster_n": 4},
        "packets": [
            {"index": 1, "pages": [8, 15], "flags": []},
            {"index": 0, "pages": [0, 7], "flags": []},
        ],
    }
    manifests = {
        0: _manifest(0, 0),
        1: _manifest(0, 0),
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=16)

    assert proposal["expectedPacketCount"] == 4
    assert [candidate["page"] for candidate in proposal["candidateStarts"]] == [0, 8]
    assert proposal["candidateStarts"][0]["signals"] == [
        "contract-title",
        "visual",
    ]
    assert proposal["candidateStarts"][1]["signals"] == [
        "contract-title",
        "cadence",
        "visual",
    ]


def test_identity_change_is_private_and_raises_later_contract_start_confidence():
    case = {
        "id": "identity-change",
        "packets": [{"index": 0, "pages": [0, 29], "flags": []}],
    }
    manifests = {
        0: _manifest(
            0,
            10,
            boundary_evidence=[
                {
                    "page": 0,
                    "identityKey": "private-key-a",
                    "name": "Private Name A",
                    "ocrText": "private OCR text",
                },
                {
                    "page": 10,
                    "identityKey": "private-key-b",
                    "cccd": "123456789012",
                    "path": "/private/evidence.png",
                },
            ],
        )
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=30)
    later = proposal["candidateStarts"][1]

    assert later["signals"] == ["contract-title", "identity-change"]
    assert later["confidence"] == "high"
    assert {
        "private-key-a",
        "private-key-b",
        "Private Name A",
        "123456789012",
        "private OCR text",
        "/private/evidence.png",
        "/private/pg10.png",
    }.isdisjoint(str(proposal))


def test_contract_title_only_has_medium_confidence_when_identity_keys_are_empty():
    case = {
        "id": "empty-identities",
        "packets": [{"index": 0, "pages": [0, 29], "flags": []}],
    }
    manifests = {
        0: _manifest(
            0,
            10,
            boundary_evidence=[
                {"page": 0, "identityKey": ""},
                {"page": 10, "identityKey": None},
            ],
        )
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=30)

    assert proposal["candidateStarts"][1]["signals"] == ["contract-title"]
    assert proposal["candidateStarts"][1]["confidence"] == "medium"


def test_out_of_range_visual_candidate_is_not_serialized():
    case = {
        "id": "invalid-visual",
        "packets": [{"index": 0, "pages": [-1, 4], "flags": []}],
    }

    proposal = build_boundary_proposal(case, {}, total_pages=5)

    assert proposal["candidateStarts"] == []


def test_out_of_range_contract_candidate_is_not_serialized():
    case = {
        "id": "invalid-contract",
        "packets": [{"index": 0, "pages": [0, 5], "flags": []}],
    }

    proposal = build_boundary_proposal(case, {0: _manifest(6)}, total_pages=6)

    assert proposal["candidateStarts"] == [
        {
            "page": 0,
            "signals": ["visual"],
            "confidence": "medium",
            "packetIndex": 0,
            "relativePage": 0,
        }
    ]


def test_contract_starts_outside_their_originating_packet_are_discarded():
    case = {
        "id": "packet-bounded-contracts",
        "packets": [
            {
                "index": 0,
                "pages": [2, 5],
                "flags": ["length-out-of-range"],
            },
            {"index": 1, "pages": [6, 9], "flags": []},
        ],
    }
    manifests = {
        # pg4 is absolute page 6, but it belongs to packet 1 rather than the
        # packet 0 manifest that supplied it. pg8 is still inside the PDF but
        # outside every stored packet.
        0: _manifest(0, 4, 8),
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=12)

    assert [candidate["page"] for candidate in proposal["candidateStarts"]] == [2, 6]
    assert "contract-title" not in proposal["candidateStarts"][1]["signals"]


def test_out_of_packet_contracts_do_not_make_a_clear_packet_affected():
    case = {
        "id": "invalid-contract-only",
        "packets": [{"index": 0, "pages": [0, 3], "flags": []}],
    }

    proposal = build_boundary_proposal(
        case,
        {0: _manifest(4, 5)},
        total_pages=10,
    )

    assert proposal["status"] == "not_needed"
    assert proposal["affectedPacketIndexes"] == []
    assert proposal["affectedRanges"] == []


def test_malformed_manifest_never_serializes_a_candidate_without_a_location():
    case = {
        "id": "malformed-manifest",
        "packets": [{"index": 0, "pages": [0, 3], "flags": []}],
    }
    manifest = {
        "docs": [
            None,
            "private text",
            {"kind": "contract", "pages": []},
            {"kind": "contract", "pages": [None]},
            {"kind": "contract", "pages": "not-pages"},
            {"kind": "contract", "pages": [{"src": "/private/not-a-page.png"}]},
            {"kind": "contract", "pages": [{"src": "/private/pg8.png"}]},
        ],
    }

    proposal = build_boundary_proposal(case, {0: manifest}, total_pages=10)

    assert [candidate["page"] for candidate in proposal["candidateStarts"]] == [0]
    assert all(
        type(candidate.get("packetIndex")) is int
        and type(candidate.get("relativePage")) is int
        for candidate in proposal["candidateStarts"]
    )
    assert "/private/" not in str(proposal)


@pytest.mark.parametrize(
    "manifest",
    [
        {"docs": 42},
        {"docs": {"kind": "contract"}},
        {"docs": [{"kind": "contract", "pages": 42}]},
    ],
)
def test_corrupt_manifest_shapes_are_ignored(manifest):
    case = {
        "id": "corrupt-manifest-shape",
        "packets": [{"index": 0, "pages": [0, 3], "flags": []}],
    }

    proposal = build_boundary_proposal(case, {0: manifest}, total_pages=4)

    assert proposal["status"] == "not_needed"
    assert proposal["candidateStarts"] == [{
        "page": 0,
        "signals": ["visual"],
        "confidence": "medium",
        "packetIndex": 0,
        "relativePage": 0,
    }]


def test_affected_ranges_are_inclusive_bounded_and_privacy_safe():
    case = {
        "id": "affected-ranges",
        "packets": [
            {"index": 2, "pages": [0, 12], "flags": ["length-out-of-range"]},
            {
                "index": 3,
                "pages": [4, 7],
                "flags": ["length-out-of-range"],
                "name": "Private Person",
            },
            {"index": 4, "pages": [-1, 2], "flags": ["length-out-of-range"]},
            {"index": 5, "pages": [8, 12], "flags": ["length-out-of-range"]},
        ],
    }
    manifests = {
        3: {
            "docs": [{
                "kind": "contract",
                "pages": [{"src": "/private/pg0.png", "ocrText": "Private OCR"}],
            }],
        },
    }

    proposal = build_boundary_proposal(case, manifests, total_pages=10)

    assert proposal["affectedRanges"] == [{
        "packetIndex": 3,
        "startPage": 4,
        "endPage": 7,
    }]
    assert set(proposal["affectedRanges"][0]) == {
        "packetIndex", "startPage", "endPage",
    }
    page_four = next(
        candidate for candidate in proposal["candidateStarts"]
        if candidate["page"] == 4
    )
    assert (page_four["packetIndex"], page_four["relativePage"]) == (3, 0)
    for private_value in ("Private Person", "Private OCR", "/private/pg0.png"):
        assert private_value not in str(proposal)


@pytest.mark.parametrize(
    ("starts", "total_pages", "first_packet_start", "message"),
    [
        ([], 10, 0, "boundary-starts-invalid"),
        ([0, 0], 10, 0, "boundary-starts-invalid"),
        ([3, 2], 10, 2, "boundary-starts-invalid"),
        ([0, True], 10, 0, "boundary-starts-invalid"),
        ([-1, 2], 10, -1, "boundary-starts-out-of-range"),
        ([0, 10], 10, 0, "boundary-starts-out-of-range"),
        ([2, 5], 10, 3, "boundary-preamble-invalid"),
    ],
)
def test_revision_starts_reject_invalid_boundaries(
    starts, total_pages, first_packet_start, message
):
    with pytest.raises(ValueError, match=f"^{message}$"):
        validate_revision_starts(starts, total_pages, first_packet_start)


def test_revision_starts_preserve_a_valid_zero_based_partition():
    assert validate_revision_starts([2, 7, 12], 15, 2) == (2, 7, 12)
