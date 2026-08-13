import json

import pytest

from ctv_inventory_model import (
    DEFAULT_LIMITS,
    ISSUE_ORDER,
    InventoryItem,
    InventoryItemDraft,
    InventoryLimits,
    InventoryResult,
    InventoryTotals,
    assign_evidence_and_duplicate_ids,
)


def _item(*, digest=None, size=12, issues=(), **overrides):
    values = {
        "depth": 1,
        "extension": ".pdf",
        "detected_type": "pdf",
        "size": size,
        "sha256": digest,
        "hash_status": "computed" if digest else "not-applicable",
        "issue_codes": issues,
    }
    values.update(overrides)
    return InventoryItemDraft(**values)


def _result(items, *, status="complete", directories=0):
    return InventoryResult(
        inventory_version="1.0",
        inventory_status=status,
        totals=InventoryTotals(
            regular_files=sum(item.size is not None for item in items),
            directories=directories,
            issues=sum(len(item.issue_codes) for item in items),
            total_bytes=sum(item.size or 0 for item in items),
        ),
        items=items,
    )


def test_default_limits_are_the_approved_v1_values():
    assert DEFAULT_LIMITS.max_depth == 32
    assert DEFAULT_LIMITS.max_directories == 2_000
    assert DEFAULT_LIMITS.max_regular_files == 10_000
    assert DEFAULT_LIMITS.max_items == 10_000
    assert DEFAULT_LIMITS.max_entries == 12_000
    assert DEFAULT_LIMITS.sample_bytes == 16 * 1024
    assert DEFAULT_LIMITS.max_hash_file_bytes == 256 * 1024 * 1024
    assert DEFAULT_LIMITS.max_hash_total_bytes == 2 * 1024 * 1024 * 1024
    assert DEFAULT_LIMITS.max_json_bytes == 16 * 1024 * 1024


def test_exact_byte_duplicates_receive_deterministic_groups():
    digest = "a" * 64
    assigned = assign_evidence_and_duplicate_ids(
        (_item(digest=digest), _item(digest=digest), _item(digest="b" * 64))
    )
    assert [item.evidence_id for item in assigned] == [
        "evidence-0001", "evidence-0002", "evidence-0003"
    ]
    assert [item.duplicate_group_id for item in assigned] == [
        "duplicate-0001", "duplicate-0001", None
    ]


def test_inventory_result_serializes_the_exact_private_safe_shape():
    items = assign_evidence_and_duplicate_ids(
        (_item(issues=("type-extension-mismatch",)),)
    )
    result = _result(items, status="complete-with-issues", directories=2)
    payload = result.to_dict()
    assert payload["inventoryVersion"] == "1.0"
    assert payload["inventoryStatus"] == "complete-with-issues"
    assert payload["totals"] == {
        "regularFiles": 1,
        "directories": 2,
        "issues": 1,
        "totalBytes": 12,
    }
    assert set(payload["items"][0]) == {
        "evidenceId", "depth", "extension", "detectedType", "size",
        "sha256", "hashStatus", "duplicateGroupId", "issueCodes",
    }
    assert "/" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"inventory_version": "2.0"}, "inventory_version"),
        ({"inventory_status": "incomplete"}, "inventory_status"),
    ],
)
def test_result_rejects_invalid_version_or_status(kwargs, message):
    with pytest.raises(ValueError, match=message):
        InventoryResult(
            inventory_version=kwargs.get("inventory_version", "1.0"),
            inventory_status=kwargs.get("inventory_status", "complete"),
            totals=InventoryTotals(0, 0, 0, 0),
            items=(),
        )


@pytest.mark.parametrize(
    ("status", "items"),
    [
        ("complete", assign_evidence_and_duplicate_ids((_item(issues=("unreadable",)),))),
        ("complete-with-issues", ()),
    ],
)
def test_result_requires_status_to_agree_with_issues(status, items):
    with pytest.raises(ValueError, match="inventory_status"):
        _result(items, status=status)


@pytest.mark.parametrize(
    "totals",
    [
        InventoryTotals(0, 0, 0, 12),
        InventoryTotals(1, 0, 1, 12),
        InventoryTotals(1, 0, 0, 11),
    ],
)
def test_result_rejects_totals_that_disagree_with_items(totals):
    items = assign_evidence_and_duplicate_ids((_item(),))
    with pytest.raises(ValueError, match="totals"):
        InventoryResult("1.0", "complete", totals, items)


@pytest.mark.parametrize("depth", [0, 33])
def test_item_rejects_depth_outside_approved_range(depth):
    with pytest.raises(ValueError, match="depth"):
        _item(depth=depth)


@pytest.mark.parametrize("extension", [".PDF", ".verylongext", "txt", ".x/y"])
def test_item_rejects_unsafe_extension(extension):
    with pytest.raises(ValueError, match="extension"):
        _item(extension=extension)


@pytest.mark.parametrize(
    ("field", "value"),
    [("detected_type", "word"), ("hash_status", "pending")],
)
def test_item_rejects_invalid_literal_domains(field, value):
    with pytest.raises(ValueError, match=field):
        _item(**{field: value})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sha256": "A" * 64, "hash_status": "computed"},
        {"sha256": "a" * 63, "hash_status": "computed"},
        {"sha256": "a" * 64, "hash_status": "not-applicable"},
        {"sha256": None, "hash_status": "computed"},
    ],
)
def test_item_validates_digest_and_hash_status_pair(kwargs):
    with pytest.raises(ValueError, match="sha256"):
        _item(**kwargs)


def test_final_item_rejects_duplicate_group_without_computed_digest():
    with pytest.raises(ValueError, match="duplicate_group_id"):
        InventoryItem(
            "evidence-0001", 1, ".pdf", "pdf", 12, None,
            "not-applicable", "duplicate-0001", (),
        )


@pytest.mark.parametrize(
    "values",
    [
        (-1, 0, 0, 0),
        (0, -1, 0, 0),
        (0, 0, -1, 0),
        (0, 0, 0, -1),
    ],
)
def test_totals_reject_negative_counts_or_sizes(values):
    with pytest.raises(ValueError, match="non-negative"):
        InventoryTotals(*values)


def test_item_rejects_negative_size_and_result_rejects_more_than_limit():
    with pytest.raises(ValueError, match="size"):
        _item(size=-1)
    item = InventoryItem(
        "evidence-0001", 1, ".pdf", "pdf", 0, None, "not-applicable", None, ()
    )
    with pytest.raises(ValueError, match="max_items"):
        InventoryResult(
            "1.0", "complete", InventoryTotals(10_001, 0, 0, 0), (item,) * 10_001
        )


@pytest.mark.parametrize(
    "issues",
    [
        ("not_allowed",),
        ("unreadable", "unreadable"),
        ("type-extension-mismatch", "unreadable"),
    ],
)
def test_item_rejects_invalid_duplicate_or_unordered_issue_codes(issues):
    with pytest.raises(ValueError, match="issue_codes"):
        _item(issues=issues)


def test_issue_order_is_the_approved_stable_order():
    assert ISSUE_ORDER == (
        "symlink", "special-file", "unreadable", "changed-during-read",
        "type-detection-failed", "type-extension-mismatch",
        "hash-skipped-too-large", "hash-budget-exhausted",
    )


def test_models_defensively_copy_mutable_caller_values_and_to_dict_output():
    issues = ["unreadable"]
    draft = _item(issues=issues)
    issues.append("hash-budget-exhausted")
    assert draft.issue_codes == ("unreadable",)

    item = assign_evidence_and_duplicate_ids((draft,))[0]
    items = [item]
    result = _result(items, status="complete-with-issues")
    items.clear()
    payload = result.to_dict()
    payload["items"][0]["issueCodes"].append("changed-during-read")
    assert result.items[0].issue_codes == ("unreadable",)


def test_duplicate_grouping_excludes_size_mismatch_missing_digest_and_changed_items():
    digest = "a" * 64
    assigned = assign_evidence_and_duplicate_ids(
        (
            _item(digest=digest, size=12),
            _item(digest=digest, size=13),
            _item(),
            _item(digest=digest, issues=("changed-during-read",)),
        )
    )
    assert [item.duplicate_group_id for item in assigned] == [None, None, None, None]


def test_limits_reject_non_positive_values():
    with pytest.raises(ValueError, match="positive"):
        InventoryLimits(max_depth=0)
