"""Exact-only roster resolution for the local CCCD mapping spike.

This module deliberately makes no packet or production-store decision.  It
classifies a paired card candidate conservatively so the spike can measure
only safe automatic candidates against a fixed roster denominator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from cccd_pairing import CardCandidate
from ocr_extract import norm


ResolutionState: TypeAlias = Literal["exact", "suggested", "manual", "conflict"]
MatchMethod: TypeAlias = Literal["cccd", "name"]

_AUTO_CCCD_CONFIDENCE = 0.85
_SUGGESTED_NAME_CONFIDENCE = 0.80


@dataclass(frozen=True)
class CardResolution:
    candidate_id: str
    state: ResolutionState
    roster_key: str | None
    matched_by: MatchMethod | None
    issues: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionResult:
    expected_mappable_identities: int
    resolutions: list[CardResolution]


def resolve_candidates(
    candidates: list[CardCandidate],
    roster_rows: list[dict[str, str]],
) -> ResolutionResult:
    """Resolve only unambiguous region-located CCCD reads automatically.

    A roster row's opaque key is derived solely from its input order.  No
    automatic outcome is produced if the same roster identity has competing
    card claims, or if any CCCD/name evidence is duplicated or conflicts.
    """
    by_cccd = _index_many(roster_rows, lambda row: _digits(row.get("cccd", "")))
    by_name = _index_many(roster_rows, lambda row: _name_key(row.get("name", "")))
    expected = _expected_mappable_identities(by_cccd)
    if expected == 0:
        raise ValueError("at least one eligible roster identity is required")

    claims_by_candidate = {
        candidate.id: _candidate_claims(candidate, by_cccd, by_name)
        for candidate in candidates
    }
    claims_by_target = _claims_by_target(claims_by_candidate)

    resolutions = [
        _resolve_one(candidate, roster_rows, by_cccd, by_name, claims_by_candidate[candidate.id], claims_by_target)
        for candidate in candidates
    ]
    return ResolutionResult(expected_mappable_identities=expected, resolutions=resolutions)


def _index_many(rows, key_fn):
    out = {}
    for index, row in enumerate(rows):
        key = key_fn(row)
        if key:
            out.setdefault(key, []).append((index, row))
    return out


def _digits(value: str | None) -> str:
    return "".join(character for character in value or "" if character.isdigit())


def _name_key(value: str | None) -> str:
    return norm(value or "") if value and value.strip() else ""


def _expected_mappable_identities(by_cccd) -> int:
    return sum(1 for cccd in by_cccd if len(cccd) == 12)


def _front_ocr(candidate: CardCandidate):
    if candidate.front is None or candidate.front.ocr.side != "front":
        return None
    return candidate.front.ocr


def _candidate_claims(candidate, by_cccd, by_name) -> set[int]:
    """Return the unique roster identities the candidate can plausibly target.

    Claims are intentionally broader than automatic matches: a low-confidence
    but region-located 12-digit read still competes with a high-confidence
    read of the same identity, preventing either from becoming automatic.
    """
    ocr = _front_ocr(candidate)
    if ocr is None:
        return set()

    claims: set[int] = set()
    cccd = _digits(ocr.cccd)
    if ocr.number_bbox is not None:
        cccd_matches = by_cccd.get(cccd, []) if len(cccd) == 12 else []
        if len(cccd_matches) == 1:
            claims.add(cccd_matches[0][0])

    name = _name_key(ocr.name)
    name_matches = by_name.get(name, []) if ocr.name_confidence >= _SUGGESTED_NAME_CONFIDENCE else []
    if len(name_matches) == 1 and _is_unique_eligible_identity(name_matches[0][0], by_cccd):
        claims.add(name_matches[0][0])
    return claims


def _is_unique_eligible_identity(index: int, by_cccd) -> bool:
    for cccd, matches in by_cccd.items():
        if len(cccd) == 12 and len(matches) == 1 and matches[0][0] == index:
            return True
    return False


def _claims_by_target(claims_by_candidate: dict[str, set[int]]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for candidate_id, targets in claims_by_candidate.items():
        for target in targets:
            out.setdefault(target, set()).add(candidate_id)
    return out


def _resolve_one(candidate, roster_rows, by_cccd, by_name, claims, claims_by_target) -> CardResolution:
    issues = list(candidate.issues)
    ocr = _front_ocr(candidate)
    if ocr is None:
        return _manual(candidate.id, issues, "no-front")
    if "ambiguous-pair" in issues:
        return _conflict(candidate.id, issues, "ambiguous-pair")
    if ocr.number_bbox is None:
        return _resolve_name_only(candidate.id, ocr, issues, by_cccd, by_name, claims, claims_by_target)

    cccd = _digits(ocr.cccd)
    if cccd and len(cccd) != 12:
        return _manual(candidate.id, issues, "non-12-digit-cccd")

    cccd_matches = by_cccd.get(cccd, []) if len(cccd) == 12 else []
    if len(cccd_matches) > 1:
        return _conflict(candidate.id, issues, "duplicate-cccd")

    name = _name_key(ocr.name)
    name_matches = by_name.get(name, []) if ocr.name_confidence >= _SUGGESTED_NAME_CONFIDENCE else []
    if len(name_matches) > 1:
        return _conflict(candidate.id, issues, "duplicate-name")

    cccd_target = cccd_matches[0][0] if len(cccd_matches) == 1 else None
    name_target = name_matches[0][0] if len(name_matches) == 1 else None
    if cccd_target is not None and _roster_name_is_duplicate(cccd_target, roster_rows, by_name):
        return _conflict(candidate.id, issues, "duplicate-name")
    if cccd_target is not None and name_target is not None and cccd_target != name_target:
        return _conflict(candidate.id, issues, "conflicting-identity")

    for target in claims:
        if len(claims_by_target[target]) > 1:
            return _conflict(candidate.id, issues, "competing-candidate")

    if cccd_target is not None and ocr.cccd_confidence >= _AUTO_CCCD_CONFIDENCE:
        return _resolved(candidate.id, "exact", cccd_target, "cccd", issues)
    if name_target is not None and _is_unique_eligible_identity(name_target, by_cccd):
        return _resolved(candidate.id, "suggested", name_target, "name", issues)
    if not cccd:
        return _manual(candidate.id, issues, "unreadable-identity")
    if cccd_target is not None and ocr.cccd_confidence < _AUTO_CCCD_CONFIDENCE:
        return _manual(candidate.id, issues, "low-cccd-confidence")
    return _manual(candidate.id, issues, "no-exact-roster-match")


def _resolve_name_only(candidate_id, ocr, issues, by_cccd, by_name, claims, claims_by_target) -> CardResolution:
    name = _name_key(ocr.name)
    name_matches = by_name.get(name, []) if ocr.name_confidence >= _SUGGESTED_NAME_CONFIDENCE else []
    if len(name_matches) > 1:
        return _conflict(candidate_id, issues, "duplicate-name")
    if len(name_matches) == 1:
        target = name_matches[0][0]
        if len(claims_by_target.get(target, set())) > 1:
            return _conflict(candidate_id, issues, "competing-candidate")
        if _is_unique_eligible_identity(target, by_cccd):
            return _resolved(candidate_id, "suggested", target, "name", _with_issue(issues, "no-number-region"))
    return _manual(candidate_id, issues, "no-number-region")


def _roster_name_is_duplicate(index: int, roster_rows, by_name) -> bool:
    key = _name_key(roster_rows[index].get("name", ""))
    return bool(key and len(by_name.get(key, [])) > 1)


def _resolved(candidate_id, state, roster_index, matched_by, issues) -> CardResolution:
    return CardResolution(candidate_id, state, f"roster-{roster_index}", matched_by, tuple(issues))


def _manual(candidate_id, issues, issue) -> CardResolution:
    return CardResolution(candidate_id, "manual", None, None, _with_issue(issues, issue))


def _conflict(candidate_id, issues, issue) -> CardResolution:
    return CardResolution(candidate_id, "conflict", None, None, _with_issue(issues, issue))


def _with_issue(issues: list[str], issue: str) -> tuple[str, ...]:
    return tuple(issues if issue in issues else [*issues, issue])
