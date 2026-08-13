"""Private-safe immutable values for a read-only CTV folder inventory."""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


InventoryStatus = Literal["complete", "complete-with-issues"]
DetectedType = Literal["pdf", "xlsx", "zip", "rar", "image", "unknown"]
HashStatus = Literal[
    "computed", "skipped-too-large", "budget-exhausted", "not-applicable"
]

ISSUE_ORDER: tuple[str, ...] = (
    "symlink",
    "special-file",
    "unreadable",
    "changed-during-read",
    "type-detection-failed",
    "type-extension-mismatch",
    "hash-skipped-too-large",
    "hash-budget-exhausted",
)

_EXTENSION = re.compile(r"^(?:unknown|\.[a-z0-9]{1,10})$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")
_DUPLICATE_GROUP_ID = re.compile(r"^duplicate-[0-9]{4,}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ISSUE_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DETECTED_TYPES = frozenset({"pdf", "xlsx", "zip", "rar", "image", "unknown"})
_HASH_STATUSES = frozenset(
    {"computed", "skipped-too-large", "budget-exhausted", "not-applicable"}
)
_ISSUE_POSITIONS = {issue: position for position, issue in enumerate(ISSUE_ORDER)}


@dataclass(frozen=True)
class InventoryLimits:
    max_depth: int = 32
    max_directories: int = 2_000
    max_regular_files: int = 10_000
    max_items: int = 10_000
    max_entries: int = 12_000
    sample_bytes: int = 16 * 1024
    max_hash_file_bytes: int = 256 * 1024 * 1024
    max_hash_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_json_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        for value in (
            self.max_depth,
            self.max_directories,
            self.max_regular_files,
            self.max_items,
            self.max_entries,
            self.sample_bytes,
            self.max_hash_file_bytes,
            self.max_hash_total_bytes,
            self.max_json_bytes,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("inventory limits must be positive integers")


DEFAULT_LIMITS = InventoryLimits()


def _validate_item_values(
    *,
    depth: int,
    extension: str,
    detected_type: str,
    size: int | None,
    sha256: str | None,
    hash_status: str,
    issue_codes: Sequence[str],
) -> tuple[str, ...]:
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 32:
        raise ValueError("depth must be within 1..32")
    if not isinstance(extension, str) or not _EXTENSION.fullmatch(extension):
        raise ValueError("extension must be safe")
    if detected_type not in _DETECTED_TYPES:
        raise ValueError("detected_type must be supported")
    if size is not None and (
        not isinstance(size, int) or isinstance(size, bool) or size < 0
    ):
        raise ValueError("size must be non-negative or null")
    if hash_status not in _HASH_STATUSES:
        raise ValueError("hash_status must be supported")
    if hash_status == "computed":
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest when computed")
    elif sha256 is not None:
        raise ValueError("sha256 must be absent unless computed")

    if isinstance(issue_codes, str):
        raise ValueError("issue_codes must be a sequence")
    copied_issue_codes = tuple(copy.deepcopy(tuple(issue_codes)))
    if any(
        not isinstance(code, str)
        or not _ISSUE_CODE.fullmatch(code)
        or code not in _ISSUE_POSITIONS
        for code in copied_issue_codes
    ):
        raise ValueError("issue_codes must be approved lower-case kebab case")
    if len(set(copied_issue_codes)) != len(copied_issue_codes):
        raise ValueError("issue_codes must not contain duplicates")
    if tuple(sorted(copied_issue_codes, key=_ISSUE_POSITIONS.__getitem__)) != copied_issue_codes:
        raise ValueError("issue_codes must follow ISSUE_ORDER")
    return copied_issue_codes


@dataclass(frozen=True)
class InventoryItemDraft:
    """An internal item assembled before public opaque IDs are assigned."""

    depth: int
    extension: str
    detected_type: DetectedType
    size: int | None
    sha256: str | None
    hash_status: HashStatus
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        issue_codes = _validate_item_values(
            depth=self.depth,
            extension=self.extension,
            detected_type=self.detected_type,
            size=self.size,
            sha256=self.sha256,
            hash_status=self.hash_status,
            issue_codes=self.issue_codes,
        )
        object.__setattr__(self, "issue_codes", issue_codes)


@dataclass(frozen=True)
class InventoryItem:
    """A final public item with no source path or filename."""

    evidence_id: str
    depth: int
    extension: str
    detected_type: DetectedType
    size: int | None
    sha256: str | None
    hash_status: HashStatus
    duplicate_group_id: str | None
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, str) or not _EVIDENCE_ID.fullmatch(
            self.evidence_id
        ):
            raise ValueError("evidence_id must be an opaque evidence ID")
        issue_codes = _validate_item_values(
            depth=self.depth,
            extension=self.extension,
            detected_type=self.detected_type,
            size=self.size,
            sha256=self.sha256,
            hash_status=self.hash_status,
            issue_codes=self.issue_codes,
        )
        if self.duplicate_group_id is not None:
            if (
                not isinstance(self.duplicate_group_id, str)
                or not _DUPLICATE_GROUP_ID.fullmatch(self.duplicate_group_id)
            ):
                raise ValueError("duplicate_group_id must be an opaque duplicate ID")
            if self.hash_status != "computed" or self.sha256 is None:
                raise ValueError("duplicate_group_id requires a computed digest")
        object.__setattr__(self, "issue_codes", issue_codes)

    def to_dict(self) -> dict[str, object]:
        return {
            "evidenceId": self.evidence_id,
            "depth": self.depth,
            "extension": self.extension,
            "detectedType": self.detected_type,
            "size": self.size,
            "sha256": self.sha256,
            "hashStatus": self.hash_status,
            "duplicateGroupId": self.duplicate_group_id,
            "issueCodes": copy.deepcopy(list(self.issue_codes)),
        }


@dataclass(frozen=True)
class InventoryTotals:
    regular_files: int
    directories: int
    issues: int
    total_bytes: int

    def __post_init__(self) -> None:
        for value in (
            self.regular_files,
            self.directories,
            self.issues,
            self.total_bytes,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("inventory totals must be non-negative integers")

    def to_dict(self) -> dict[str, object]:
        return {
            "regularFiles": self.regular_files,
            "directories": self.directories,
            "issues": self.issues,
            "totalBytes": self.total_bytes,
        }


@dataclass(frozen=True)
class InventoryResult:
    inventory_version: str
    inventory_status: InventoryStatus
    totals: InventoryTotals
    items: Sequence[InventoryItem]

    def __post_init__(self) -> None:
        if self.inventory_version != "1.0":
            raise ValueError("inventory_version must be 1.0")
        if self.inventory_status not in {"complete", "complete-with-issues"}:
            raise ValueError("inventory_status must be complete or complete-with-issues")
        if not isinstance(self.totals, InventoryTotals):
            raise ValueError("totals must be InventoryTotals")
        if isinstance(self.items, str):
            raise ValueError("items must be a sequence")
        items = tuple(copy.deepcopy(tuple(self.items)))
        if not all(isinstance(item, InventoryItem) for item in items):
            raise ValueError("items must contain InventoryItem values")
        if len(items) > DEFAULT_LIMITS.max_items:
            raise ValueError("items must not exceed max_items")

        expected_regular_files = sum(item.size is not None for item in items)
        expected_issues = sum(len(item.issue_codes) for item in items)
        expected_total_bytes = sum(item.size or 0 for item in items)
        if (
            self.totals.regular_files != expected_regular_files
            or self.totals.issues != expected_issues
            or self.totals.total_bytes != expected_total_bytes
        ):
            raise ValueError("totals must agree with items")
        if self.inventory_status == "complete" and expected_issues:
            raise ValueError("inventory_status complete requires zero issues")
        if self.inventory_status == "complete-with-issues" and not expected_issues:
            raise ValueError("inventory_status complete-with-issues requires issues")
        object.__setattr__(self, "items", items)

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy(
            {
                "inventoryVersion": self.inventory_version,
                "inventoryStatus": self.inventory_status,
                "totals": self.totals.to_dict(),
                "items": [item.to_dict() for item in self.items],
            }
        )


def assign_evidence_and_duplicate_ids(
    items: Sequence[InventoryItemDraft],
) -> tuple[InventoryItem, ...]:
    """Assign opaque IDs without exposing or depending on caller-visible sort keys."""
    drafts = tuple(items)
    if not all(isinstance(item, InventoryItemDraft) for item in drafts):
        raise ValueError("items must contain InventoryItemDraft values")

    duplicate_members: dict[tuple[int | None, str], list[int]] = {}
    for index, draft in enumerate(drafts):
        if (
            draft.hash_status == "computed"
            and draft.sha256 is not None
            and "changed-during-read" not in draft.issue_codes
        ):
            duplicate_members.setdefault((draft.size, draft.sha256), []).append(index)

    group_ids: dict[int, str] = {}
    group_number = 1
    for member_indexes in duplicate_members.values():
        if len(member_indexes) >= 2:
            group_id = f"duplicate-{group_number:04d}"
            for index in member_indexes:
                group_ids[index] = group_id
            group_number += 1

    return tuple(
        InventoryItem(
            evidence_id=f"evidence-{index + 1:04d}",
            depth=draft.depth,
            extension=draft.extension,
            detected_type=draft.detected_type,
            size=draft.size,
            sha256=draft.sha256,
            hash_status=draft.hash_status,
            duplicate_group_id=group_ids.get(index),
            issue_codes=draft.issue_codes,
        )
        for index, draft in enumerate(drafts)
    )
