"""Exact-only, case-local CCCD planning and v1 evidence attachment."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import tempfile
from typing import Callable, TypedDict

from cccd_matching import (
    CardResolution,
    ResolutionResult,
    resolve_candidates,
)
from cccd_ocr import EvidenceWriteBudget, analyze_drawing
from cccd_pairing import (
    AnalyzedDrawing,
    CardCandidate,
    pair_drawings,
)
from cccd_workbook import extract_drawings


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


def _digits(value: object) -> str:
    return (
        "".join(character for character in value if character.isdigit())
        if isinstance(value, str)
        else ""
    )


def _roster_index(roster_key: str | None) -> int | None:
    if not roster_key or not roster_key.startswith("roster-"):
        return None
    raw = roster_key.removeprefix("roster-")
    return int(raw) if raw.isdigit() else None


def _case_relative(case_dir: str, path: str) -> str:
    root = os.path.realpath(case_dir)
    candidate = os.path.realpath(path)
    try:
        shared_path = os.path.commonpath([root, candidate])
    except ValueError as error:
        raise ValueError("CCCD asset escaped case directory") from error
    if shared_path != root:
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
            "fromRowOffset": anchor.from_row_offset,
            "fromColOffset": anchor.from_col_offset,
            "toRowOffset": anchor.to_row_offset,
            "toColOffset": anchor.to_col_offset,
        },
    }


def _append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _packet_target_index(
    packet: object,
    roster_cccd: str,
) -> int | None:
    if not isinstance(packet, dict):
        return None
    index = packet.get("index")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or index < 0
    ):
        return None
    identity = packet.get("rosterIdentity")
    if not isinstance(identity, dict):
        return None
    return (
        index
        if _digits(identity.get("cccd")) == roster_cccd
        else None
    )


def _validated_candidate_resolution_maps(
    candidates: list[CardCandidate],
    resolution_result: ResolutionResult,
) -> tuple[dict[str, CardCandidate], dict[str, CardResolution]]:
    candidate_by_id = {
        candidate.id: candidate for candidate in candidates
    }
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
        index
        for packet in packets
        if (
            index := _packet_target_index(packet, roster_cccd)
        ) is not None
    ]
    if len(targets) == 1:
        return targets[0]
    _append_issue(
        issues,
        (
            "packet-target-not-found"
            if not targets
            else "non-unique-packet-target"
        ),
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
    candidate_by_id, resolution_by_id = (
        _validated_candidate_resolution_maps(candidates, resolution_result)
    )
    planned = []
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        resolution = resolution_by_id[candidate_id]
        front_ocr = (
            candidate.front.ocr
            if candidate.front is not None
            else None
        )
        provenance_ocr = (
            front_ocr
            if front_ocr is not None
            else (
                candidate.unknown.ocr
                if candidate.unknown is not None
                else None
            )
        )
        issues = list(
            dict.fromkeys((*candidate.issues, *resolution.issues))
        )
        target_packet_index = _target_packet_index(
            resolution,
            roster_rows,
            packets,
            issues,
        )
        if candidate.front is None:
            _append_issue(issues, "missing-front")
            target_packet_index = None
        if candidate.back is None:
            _append_issue(issues, "missing-back")
            target_packet_index = None
        mapping = {
            "candidateId": candidate.id,
            "front": _serialize_side(candidate.front, case_dir),
            "back": _serialize_side(candidate.back, case_dir),
            "unknown": _serialize_side(candidate.unknown, case_dir),
            "ocrIdentity": {
                "cccd": (
                    provenance_ocr.cccd
                    if provenance_ocr is not None
                    else ""
                ),
                "name": (
                    provenance_ocr.name
                    if provenance_ocr is not None
                    else ""
                ),
            },
            "ocrConfidence": {
                "cccd": (
                    provenance_ocr.cccd_confidence
                    if provenance_ocr is not None
                    else 0.0
                ),
                "name": (
                    provenance_ocr.name_confidence
                    if provenance_ocr is not None
                    else 0.0
                ),
            },
            "numberBbox": (
                provenance_ocr.number_bbox
                if provenance_ocr is not None
                else None
            ),
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


def _atomic_json_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".manifest-",
        suffix=".json",
        dir=directory,
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _owned_doc_id(candidate_id: str, side: str) -> str:
    return f"cccd-excel-{candidate_id}-{side}"


def _packet_filename(
    plan: PlannedMapping,
    analyzed,
    side: str,
) -> str:
    candidate_token = hashlib.sha256(
        plan.candidate.id.encode("utf-8")
    ).hexdigest()[:12]
    image_token = analyzed.drawing.sha256[:12]
    orientation_token = (
        "-upright"
        if analyzed.ocr.evidence_path is not None
        else ""
    )
    return (
        f"cccd-{candidate_token}-{image_token}{orientation_token}-{side}."
        f"{analyzed.drawing.extension}"
    )


def _attachment_failure(plan: PlannedMapping) -> dict:
    mapping = deepcopy(plan.mapping)
    issues = list(mapping.get("issues", []))
    _append_issue(issues, "attachment-failed")
    mapping["issues"] = issues
    mapping["attachedPacketIndex"] = None
    return mapping


def _remove_stale_owned_files(
    old_documents,
    packet_dir: str,
    new_paths: set[str],
) -> None:
    real_packet_dir = os.path.realpath(packet_dir)
    for document in old_documents:
        if not isinstance(document, dict):
            continue
        pages = document.get("pages")
        if not isinstance(pages, list):
            continue
        for page in pages:
            source = (
                page.get("src")
                if isinstance(page, dict)
                else None
            )
            if not isinstance(source, str):
                continue
            old_path = os.path.realpath(source)
            if (
                os.path.dirname(old_path) == real_packet_dir
                and old_path not in new_paths
                and os.path.basename(old_path).startswith("cccd-")
                and os.path.isfile(old_path)
            ):
                os.unlink(old_path)


def _is_owned_doc_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith("cccd-excel-")


def _kept_owned_ids_by_packet(mappings: list[dict]) -> dict[int, set[str]]:
    kept: dict[int, set[str]] = {}
    for mapping in mappings:
        packet_index = mapping.get("attachedPacketIndex")
        candidate_id = mapping.get("candidateId")
        if (
            not isinstance(packet_index, int)
            or isinstance(packet_index, bool)
            or packet_index < 0
            or not isinstance(candidate_id, str)
        ):
            continue
        kept.setdefault(packet_index, set()).update({
            _owned_doc_id(candidate_id, "front"),
            _owned_doc_id(candidate_id, "back"),
        })
    return kept


def _reconcile_manifest_owned_evidence(
    manifest_path: str,
    case_dir: str,
    keep_ids: set[str],
) -> bool:
    try:
        _case_relative(case_dir, manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as handle:
            original = json.load(handle)
        if not isinstance(original, dict):
            raise ValueError("manifest must be an object")
        updated = deepcopy(original)
        docs = updated.get("docs")
        fields = updated.get("fields")
        if not isinstance(docs, list) or not isinstance(fields, list):
            raise ValueError("manifest structure is invalid")
        removed_docs = [
            document
            for document in docs
            if (
                isinstance(document, dict)
                and _is_owned_doc_id(document.get("id"))
                and document.get("id") not in keep_ids
            )
        ]
        updated["docs"] = [
            document
            for document in docs
            if not (
                isinstance(document, dict)
                and _is_owned_doc_id(document.get("id"))
                and document.get("id") not in keep_ids
            )
        ]
        changed = bool(removed_docs)
        for field in fields:
            if not isinstance(field, dict):
                continue
            sources = field.get("sources")
            if not isinstance(sources, list):
                continue
            kept_sources = [
                source
                for source in sources
                if not (
                    isinstance(source, dict)
                    and _is_owned_doc_id(source.get("docId"))
                    and source.get("docId") not in keep_ids
                )
            ]
            if len(kept_sources) != len(sources):
                field["sources"] = kept_sources
                changed = True
        if changed:
            _atomic_json_write(manifest_path, updated)
            _remove_stale_owned_files(
                removed_docs,
                os.path.dirname(manifest_path),
                set(),
            )
        return True
    except Exception:
        return False


def _reconcile_owned_evidence(
    manifest_paths: dict[int, str],
    case_dir: str,
    mappings: list[dict],
) -> bool:
    kept_by_packet = _kept_owned_ids_by_packet(mappings)
    successful = True
    for packet_index, manifest_path in manifest_paths.items():
        if (
            not isinstance(packet_index, int)
            or isinstance(packet_index, bool)
            or packet_index < 0
            or not isinstance(manifest_path, str)
        ):
            successful = False
            continue
        successful = (
            _reconcile_manifest_owned_evidence(
                manifest_path,
                case_dir,
                kept_by_packet.get(packet_index, set()),
            )
            and successful
        )
    return successful


def _cleanup_attempt_files(paths: list[str]) -> bool:
    failed = False
    for path in paths:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except Exception:
            failed = True
    return failed


def _is_exact_attachment_plan(plan: PlannedMapping) -> bool:
    target = plan.target_packet_index
    return (
        isinstance(target, int)
        and not isinstance(target, bool)
        and target >= 0
        and getattr(plan.resolution, "state", None) == "exact"
        and isinstance(plan.mapping, dict)
        and plan.mapping.get("state") == "exact"
        and plan.candidate.front is not None
        and plan.candidate.back is not None
        and isinstance(plan.mapping.get("front"), dict)
        and isinstance(plan.mapping.get("back"), dict)
    )


def _report_progress(
    progress_cb: ProgressCallback,
    done: int,
    total: int,
) -> None:
    try:
        progress_cb("cccd", done, total, "")
    except Exception:
        pass


def _error_result(
    packets: list[dict],
    error_code: str,
) -> CccdIngestResult:
    return {
        "packets": packets,
        "cccdWorkbook": {
            "status": "error",
            "errorCode": error_code,
            "summary": {
                "candidates": 0,
                "attached": 0,
                "unresolved": 0,
            },
            "mappings": [],
        },
    }


def _reconciled_error_result(
    packets: list[dict],
    error_code: str,
    manifest_paths: dict[int, str],
    case_dir: str,
) -> CccdIngestResult:
    if not _reconcile_owned_evidence(manifest_paths, case_dir, []):
        error_code = "attachment-failed"
    return _error_result(packets, error_code)


def _packet_by_index(packets: list[dict]) -> dict[int, dict]:
    indexed = {}
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        index = packet.get("index")
        if (
            isinstance(index, int)
            and not isinstance(index, bool)
            and index >= 0
        ):
            indexed[index] = packet
    return indexed


def ingest_cccd_workbook(
    xlsx_path: str,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    case_dir: str,
    packet_manifest_paths: dict[int, str],
    assets_dir: str,
    progress_cb: ProgressCallback,
) -> CccdIngestResult:
    """Run local CCCD ingestion and preserve partial usable results."""
    manifest_paths = (
        packet_manifest_paths
        if isinstance(packet_manifest_paths, dict)
        else {}
    )
    try:
        extraction = extract_drawings(
            xlsx_path,
            os.path.join(assets_dir, "extracted"),
        )
    except Exception:
        return _reconciled_error_result(
            packets,
            "invalid-workbook",
            manifest_paths,
            case_dir,
        )
    if not extraction.drawings:
        return _reconciled_error_result(
            packets,
            "no-supported-images",
            manifest_paths,
            case_dir,
        )

    analyzed = []
    ocr_failures = 0
    evidence_budget = EvidenceWriteBudget()
    for drawing in extraction.drawings:
        try:
            analyzed.append(
                AnalyzedDrawing(
                    drawing,
                    analyze_drawing(drawing, evidence_budget),
                )
            )
        except Exception:
            ocr_failures += 1
    if not analyzed:
        return _reconciled_error_result(
            packets,
            "ocr-unavailable",
            manifest_paths,
            case_dir,
        )

    try:
        candidates = pair_drawings(analyzed)
        resolution_result = resolve_candidates(
            candidates,
            roster_rows,
        )
        plans = plan_candidate_mappings(
            candidates,
            resolution_result,
            roster_rows,
            packets,
            case_dir,
        )
    except Exception:
        return _reconciled_error_result(
            packets,
            "invalid-workbook",
            manifest_paths,
            case_dir,
        )

    packet_by_index = _packet_by_index(packets)
    mappings = []
    for done, planned in enumerate(plans, start=1):
        if planned.target_packet_index is None:
            mapping = deepcopy(planned.mapping)
        else:
            target_packet = packet_by_index.get(
                planned.target_packet_index
            )
            manifest_path = manifest_paths.get(
                planned.target_packet_index
            )
            mapping = (
                attach_planned_mapping(
                    planned,
                    target_packet,
                    manifest_path,
                    case_dir,
                )
                if target_packet is not None
                and isinstance(manifest_path, str)
                else _attachment_failure(planned)
            )
        mappings.append(mapping)
        _report_progress(progress_cb, done, len(plans))

    reconciliation_failed = not _reconcile_owned_evidence(
        manifest_paths,
        case_dir,
        mappings,
    )
    attached = sum(
        mapping.get("attachedPacketIndex") is not None
        for mapping in mappings
    )
    summary = {
        "candidates": len(mappings),
        "attached": attached,
        "unresolved": len(mappings) - attached,
    }
    if reconciliation_failed or any(
        "attachment-failed" in mapping.get("issues", [])
        for mapping in mappings
    ):
        error_code = "attachment-failed"
    elif extraction.issues:
        error_code = "extraction-incomplete"
    elif ocr_failures:
        error_code = "ocr-unavailable"
    else:
        error_code = None
    workbook = {
        "status": "partial" if error_code else "ready",
        "summary": summary,
        "mappings": mappings,
    }
    if error_code:
        workbook["errorCode"] = error_code
    return {"packets": packets, "cccdWorkbook": workbook}


def attach_planned_mapping(
    plan: PlannedMapping,
    packet: dict,
    manifest_path: str,
    case_dir: str,
) -> dict:
    """Attach one exact plan without exposing partial packet state."""
    if plan.target_packet_index is None:
        return deepcopy(plan.mapping)
    if (
        not _is_exact_attachment_plan(plan)
        or not isinstance(packet, dict)
        or not isinstance(packet.get("index"), int)
        or isinstance(packet.get("index"), bool)
        or packet.get("index") != plan.target_packet_index
        or not isinstance(manifest_path, str)
        or not isinstance(case_dir, str)
    ):
        return _attachment_failure(plan)

    created_files: list[str] = []
    try:
        _case_relative(case_dir, manifest_path)
        with open(
            manifest_path,
            "r",
            encoding="utf-8",
        ) as handle:
            original = json.load(handle)
        if not isinstance(original, dict):
            raise ValueError("manifest must be an object")
        updated = deepcopy(original)
        packet_dir = os.path.dirname(manifest_path)
        docs = updated.get("docs")
        fields = updated.get("fields")
        if not isinstance(docs, list) or not isinstance(fields, list):
            raise ValueError("manifest structure is invalid")
        owned_ids = {
            _owned_doc_id(plan.candidate.id, "front"),
            _owned_doc_id(plan.candidate.id, "back"),
        }
        old_owned_docs = [
            document
            for document in docs
            if (
                isinstance(document, dict)
                and document.get("id") in owned_ids
            )
        ]
        mapping = deepcopy(plan.mapping)
        new_docs = []
        new_paths: set[str] = set()
        for side in ("front", "back"):
            analyzed = getattr(plan.candidate, side)
            if analyzed is None:
                continue
            source = (
                analyzed.ocr.evidence_path
                or analyzed.drawing.stored_path
            )
            _case_relative(case_dir, source)
            destination = os.path.join(
                packet_dir,
                _packet_filename(plan, analyzed, side),
            )
            _case_relative(case_dir, destination)
            if not os.path.exists(destination):
                created_files.append(destination)
                shutil.copyfile(source, destination)
            new_paths.add(os.path.realpath(destination))
            side_mapping = mapping.get(side)
            if not isinstance(side_mapping, dict):
                raise ValueError("missing mapped side")
            side_mapping["packetPath"] = _case_relative(
                case_dir,
                destination,
            )
            new_docs.append({
                "id": _owned_doc_id(plan.candidate.id, side),
                "kind": (
                    "id_front" if side == "front" else "id_back"
                ),
                "label": (
                    "CCCD (Excel) · Mặt trước"
                    if side == "front"
                    else "CCCD (Excel) · Mặt sau"
                ),
                "pages": [{
                    "src": destination,
                    "width": (
                        analyzed.ocr.evidence_width
                        or analyzed.drawing.width
                    ),
                    "height": (
                        analyzed.ocr.evidence_height
                        or analyzed.drawing.height
                    ),
                }],
            })
        updated["docs"] = [
            document
            for document in docs
            if not (
                isinstance(document, dict)
                and document.get("id") in owned_ids
            )
        ] + new_docs
        cccd_field = next(
            field
            for field in fields
            if (
                isinstance(field, dict)
                and field.get("key") == "cccd"
            )
        )
        sources = cccd_field.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError("CCCD sources are invalid")
        cccd_field["sources"] = [
            source
            for source in sources
            if not (
                isinstance(source, dict)
                and source.get("docId") in owned_ids
            )
        ]
        front = plan.candidate.front
        if front is None or front.ocr.number_bbox is None:
            raise ValueError("exact attachment requires located front")
        cccd_field["sources"].append({
            "docId": _owned_doc_id(
                plan.candidate.id,
                "front",
            ),
            "page": 0,
            "value": front.ocr.cccd,
            "bbox": front.ocr.number_bbox,
            "confidence": front.ocr.cccd_confidence,
        })
        _atomic_json_write(manifest_path, updated)
    except Exception:
        failure = _attachment_failure(plan)
        if _cleanup_attempt_files(created_files):
            _append_issue(failure["issues"], "cleanup-failed")
        return failure

    mapping["attachedPacketIndex"] = plan.target_packet_index
    try:
        _remove_stale_owned_files(
            old_owned_docs,
            packet_dir,
            new_paths,
        )
    except Exception:
        pass
    return mapping
