"""Exact-only, case-local CCCD packet mapping plans.

This module makes no attachment or packet mutation.  It serializes card
provenance and identifies only those packet targets that are safe to attach in
a later orchestration step.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, TypedDict

from cccd_matching import CardResolution, ResolutionResult
from cccd_pairing import CardCandidate


ProgressCallback = Callable[[str, int, int, str], None]


class CccdIngestResult(TypedDict):
    packets: list[dict]
    cccdWorkbook: dict


@dataclass(frozen=True)
class PlannedMapping:
    candidate: CardCandidate
    resolution: CardResolution
    target_packet_index: int | None
    mapping: dict


def _digits(value: str | None) -> str:
    return "".join(character for character in value or "" if character.isdigit())


def _roster_index(roster_key: str | None) -> int | None:
    if not roster_key or not roster_key.startswith("roster-"):
        return None
    raw = roster_key.removeprefix("roster-")
    return int(raw) if raw.isdigit() else None


def _case_relative(case_dir: str, path: str) -> str:
    root = os.path.realpath(case_dir)
    candidate = os.path.realpath(path)
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("CCCD asset escaped case directory")
    return os.path.relpath(candidate, root).replace(os.sep, "/")


def _serialize_side(analyzed, case_dir: str) -> dict | None:
    if analyzed is None:
        return None
    drawing = analyzed.drawing
    anchor = drawing.anchor
    return {
        "drawingId": drawing.id,
        "mediaType": drawing.media_type,
        "width": drawing.width,
        "height": drawing.height,
        "sha256": drawing.sha256,
        "sourcePath": _case_relative(case_dir, drawing.stored_path),
        "packetPath": None,
        "anchor": {
            "sheet": anchor.sheet,
            "fromRow": anchor.from_row,
            "fromCol": anchor.from_col,
            "toRow": anchor.to_row,
            "toCol": anchor.to_col,
        },
    }


def _append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _validated_candidate_resolution_maps(
    candidates: list[CardCandidate], resolution_result: ResolutionResult,
) -> tuple[dict[str, CardCandidate], dict[str, CardResolution]]:
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    resolution_by_id = {
        resolution.candidate_id: resolution
        for resolution in resolution_result.resolutions
    }
    if (
        len(candidate_by_id) != len(candidates)
        or len(resolution_by_id) != len(resolution_result.resolutions)
        or set(candidate_by_id) != set(resolution_by_id)
    ):
        raise ValueError("candidate-resolution-mismatch")
    return candidate_by_id, resolution_by_id


def _target_packet_index(
    resolution: CardResolution,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    issues: list[str],
) -> int | None:
    if resolution.state != "exact":
        return None

    roster_index = _roster_index(resolution.roster_key)
    if roster_index is None or roster_index >= len(roster_rows):
        _append_issue(issues, "invalid-roster-key")
        return None

    roster_cccd = _digits(roster_rows[roster_index].get("cccd"))
    if len(roster_cccd) != 12:
        _append_issue(issues, "non-12-digit-roster-cccd")
        return None

    targets = [
        packet["index"]
        for packet in packets
        if _digits((packet.get("rosterIdentity") or {}).get("cccd")) == roster_cccd
    ]
    if len(targets) == 1:
        return targets[0]
    _append_issue(
        issues,
        "packet-target-not-found" if not targets else "non-unique-packet-target",
    )
    return None


def plan_candidate_mappings(
    candidates: list[CardCandidate],
    resolution_result: ResolutionResult,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    case_dir: str,
) -> list[PlannedMapping]:
    """Plan exact roster-to-packet matches without mutating packet state."""
    candidate_by_id, resolution_by_id = _validated_candidate_resolution_maps(
        candidates, resolution_result,
    )
    planned = []
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        resolution = resolution_by_id[candidate_id]
        front_ocr = candidate.front.ocr if candidate.front is not None else None
        issues = list(dict.fromkeys((*candidate.issues, *resolution.issues)))
        target_packet_index = _target_packet_index(
            resolution, roster_rows, packets, issues,
        )
        mapping = {
            "candidateId": candidate.id,
            "front": _serialize_side(candidate.front, case_dir),
            "back": _serialize_side(candidate.back, case_dir),
            "ocrIdentity": {
                "cccd": front_ocr.cccd if front_ocr is not None else "",
                "name": front_ocr.name if front_ocr is not None else "",
            },
            "ocrConfidence": {
                "cccd": front_ocr.cccd_confidence if front_ocr is not None else 0.0,
                "name": front_ocr.name_confidence if front_ocr is not None else 0.0,
            },
            "numberBbox": front_ocr.number_bbox if front_ocr is not None else None,
            "state": resolution.state,
            "attachedPacketIndex": None,
            "matchMethod": resolution.matched_by,
            "issues": issues,
        }
        planned.append(PlannedMapping(
            candidate=candidate,
            resolution=resolution,
            target_packet_index=target_packet_index,
            mapping=mapping,
        ))
    return planned
