from boundary_assessment import assess_case_boundaries, assess_packet_boundary
import pytest


def _manifest(*relative_contract_starts: int) -> dict:
    return {
        "docs": [
            {
                "id": f"contract-{i}",
                "kind": "contract",
                "pages": [{"src": f"/local/pg{page}.png"}],
            }
            for i, page in enumerate(relative_contract_starts)
        ],
    }


def test_multiple_contract_starts_require_boundary_review():
    packet = {
        "pages": [116, 131],
        "n_pages": 16,
        "flags": ["length-out-of-range"],
    }

    result = assess_packet_boundary(
        packet,
        _manifest(5, 13),
        {"found": 36, "roster_n": 41},
    )

    assert result == {
        "status": "review",
        "suspectedMultiplePackets": True,
        "reasons": [
            "length-out-of-range",
            "multiple-contract-starts",
            "batch-count-mismatch",
        ],
        "candidateStarts": [121, 129],
    }


def test_normal_single_contract_packet_is_clear():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}

    result = assess_packet_boundary(
        packet,
        _manifest(0),
        {"found": 4, "roster_n": 4},
    )

    assert result == {
        "status": "clear",
        "suspectedMultiplePackets": False,
        "reasons": [],
        "candidateStarts": [20],
    }


def test_batch_count_mismatch_does_not_stamp_normal_packet():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}

    result = assess_packet_boundary(
        packet,
        _manifest(0),
        {"found": 3, "roster_n": 4},
    )

    assert result["status"] == "clear"
    assert "batch-count-mismatch" not in result["reasons"]


@pytest.mark.parametrize("manifest", [None, [], {"docs": "invalid"}])
def test_malformed_manifest_does_not_invent_contract_starts(manifest):
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}

    result = assess_packet_boundary(packet, manifest, None)

    assert result["candidateStarts"] == []
    assert result["suspectedMultiplePackets"] is False


def test_duplicate_contract_start_is_counted_once():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}

    result = assess_packet_boundary(packet, _manifest(3, 3), None)

    assert result["candidateStarts"] == [23]
    assert result["status"] == "clear"


@pytest.mark.parametrize("flag", ["near-threshold", "auto-merged"])
def test_known_boundary_flag_requires_review(flag):
    packet = {"pages": [20, 27], "n_pages": 8, "flags": [flag]}

    result = assess_packet_boundary(packet, _manifest(0), None)

    assert result["status"] == "review"
    assert result["reasons"] == [flag]


def test_unknown_pipeline_flag_is_not_a_boundary_reason():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": ["synthetic-unknown"]}

    result = assess_packet_boundary(packet, _manifest(0), None)

    assert result["status"] == "clear"
    assert result["reasons"] == []


def test_case_boundary_status_blocks_only_review_packets():
    case = {
        "summary": {"found": 2, "roster_n": 2},
        "packets": [
            {"index": 0, "pages": [0, 7], "flags": []},
            {"index": 1, "pages": [8, 23], "flags": ["length-out-of-range"]},
        ],
    }
    manifests = {
        0: {"docs": [{"kind": "contract", "pages": [{"src": "pg0.png"}]}]},
        1: {"docs": [
            {"kind": "contract", "pages": [{"src": "pg0.png"}]},
            {"kind": "contract", "pages": [{"src": "pg8.png"}]},
        ]},
    }

    assert assess_case_boundaries(case, manifests) == {
        "status": "review",
        "packetIndexes": [1],
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }
