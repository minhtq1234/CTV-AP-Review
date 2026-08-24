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


def test_empty_identity_keys_never_create_identity_change_signal():
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
    assert proposal["candidateStarts"][1]["confidence"] == "low"


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
