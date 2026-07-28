"""Exact-only, case-local CCCD packet mapping plans.

This module makes no attachment or packet mutation.  It serializes card
provenance and identifies only those packet targets that are safe to attach in
a later orchestration step.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import tempfile
from typing import Callable, TypedDict

import checklist
from cccd_matching import CardResolution, ResolutionResult, resolve_candidates
from cccd_ocr import analyze_drawing
from cccd_pairing import AnalyzedDrawing, CardCandidate, pair_drawings
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
    return "".join(character for character in value if character.isdigit()) if isinstance(value, str) else ""


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
        },
    }


def _append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _packet_target_index(packet: object, roster_cccd: str) -> int | None:
    if not isinstance(packet, dict):
        return None
    index = packet.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        return None
    identity = packet.get("rosterIdentity")
    if not isinstance(identity, dict):
        return None
    return index if _digits(identity.get("cccd")) == roster_cccd else None


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
        index
        for packet in packets
        if (index := _packet_target_index(packet, roster_cccd)) is not None
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


def _atomic_json_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".manifest-", suffix=".json", dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _owned_doc_id(candidate_id: str, side: str) -> str:
    return f"cccd-excel-{candidate_id}-{side}"


def _packet_filename(plan: PlannedMapping, analyzed, side: str) -> str:
    candidate_token = hashlib.sha256(plan.candidate.id.encode("utf-8")).hexdigest()[:12]
    image_token = analyzed.drawing.sha256[:12]
    return f"cccd-{candidate_token}-{image_token}-{side}.{analyzed.drawing.extension}"


def _attachment_failure(plan: PlannedMapping) -> dict:
    mapping = deepcopy(plan.mapping)
    issues = list(mapping.get("issues", []))
    _append_issue(issues, "attachment-failed")
    mapping["issues"] = issues
    mapping["attachedPacketIndex"] = None
    return mapping


def _remove_stale_owned_files(old_documents, packet_dir: str, new_paths: set[str]) -> None:
    real_packet_dir = os.path.realpath(packet_dir)
    for document in old_documents:
        for page in document.get("pages", []):
            source = page.get("src") if isinstance(page, dict) else None
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


def _error_result(packets: list[dict], error_code: str) -> CccdIngestResult:
    return {
        "packets": packets,
        "cccdWorkbook": {
            "status": "error",
            "errorCode": error_code,
            "summary": {"candidates": 0, "attached": 0, "unresolved": 0},
            "mappings": [],
        },
    }


def _packet_by_index(packets: list[dict]) -> dict[int, dict]:
    indexed = {}
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        index = packet.get("index")
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
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
    """Run safe local CCCD ingestion and preserve partial usable results."""
    try:
        extraction = extract_drawings(xlsx_path, os.path.join(assets_dir, "extracted"))
    except Exception:
        return _error_result(packets, "invalid-workbook")
    if not extraction.drawings:
        return _error_result(packets, "no-supported-images")

    analyzed = []
    ocr_failures = 0
    for drawing in extraction.drawings:
        try:
            analyzed.append(AnalyzedDrawing(drawing, analyze_drawing(drawing)))
        except Exception:
            ocr_failures += 1
    if not analyzed:
        return _error_result(packets, "ocr-unavailable")

    try:
        candidates = pair_drawings(analyzed)
        resolution_result = resolve_candidates(candidates, roster_rows)
        plans = plan_candidate_mappings(
            candidates, resolution_result, roster_rows, packets, case_dir,
        )
    except Exception:
        return _error_result(packets, "invalid-workbook")

    packet_by_index = _packet_by_index(packets)
    manifest_paths = packet_manifest_paths if isinstance(packet_manifest_paths, dict) else {}
    mappings = []
    for done, planned in enumerate(plans, start=1):
        if planned.target_packet_index is None:
            mapping = deepcopy(planned.mapping)
        else:
            target_packet = packet_by_index.get(planned.target_packet_index)
            manifest_path = manifest_paths.get(planned.target_packet_index)
            mapping = (
                attach_planned_mapping(planned, target_packet, manifest_path, case_dir)
                if target_packet is not None and isinstance(manifest_path, str)
                else _attachment_failure(planned)
            )
        mappings.append(mapping)
        progress_cb("cccd", done, len(plans), "")

    attached = sum(mapping.get("attachedPacketIndex") is not None for mapping in mappings)
    summary = {
        "candidates": len(mappings),
        "attached": attached,
        "unresolved": len(mappings) - attached,
    }
    if any("attachment-failed" in mapping.get("issues", []) for mapping in mappings):
        error_code = "attachment-failed"
    elif extraction.issues:
        error_code = "extraction-incomplete"
    elif ocr_failures:
        error_code = "ocr-unavailable"
    else:
        error_code = None
    workbook = {"status": "partial" if error_code else "ready", "summary": summary, "mappings": mappings}
    if error_code:
        workbook["errorCode"] = error_code
    return {"packets": packets, "cccdWorkbook": workbook}


def attach_planned_mapping(
    plan: PlannedMapping,
    packet: dict,
    manifest_path: str,
    case_dir: str,
) -> dict:
    """Attach one exact plan without exposing partial packet state on failure."""
    if plan.target_packet_index is None:
        return deepcopy(plan.mapping)
    if (
        not isinstance(packet, dict)
        or packet.get("index") != plan.target_packet_index
        or not isinstance(manifest_path, str)
        or not isinstance(case_dir, str)
    ):
        return _attachment_failure(plan)

    created_files: list[str] = []
    try:
        _case_relative(case_dir, manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as handle:
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
            document for document in docs
            if isinstance(document, dict) and document.get("id") in owned_ids
        ]
        mapping = deepcopy(plan.mapping)
        new_docs = []
        new_paths: set[str] = set()
        for side in ("front", "back"):
            analyzed = getattr(plan.candidate, side)
            if analyzed is None:
                continue
            source = analyzed.drawing.stored_path
            _case_relative(case_dir, source)
            destination = os.path.join(packet_dir, _packet_filename(plan, analyzed, side))
            _case_relative(case_dir, destination)
            if not os.path.exists(destination):
                shutil.copyfile(source, destination)
                created_files.append(destination)
            new_paths.add(os.path.realpath(destination))
            side_mapping = mapping.get(side)
            if not isinstance(side_mapping, dict):
                raise ValueError("missing mapped side")
            side_mapping["packetPath"] = _case_relative(case_dir, destination)
            new_docs.append({
                "id": _owned_doc_id(plan.candidate.id, side),
                "kind": "id_front" if side == "front" else "id_back",
                "label": "CCCD (Excel) · Mặt trước" if side == "front" else "CCCD (Excel) · Mặt sau",
                "pages": [{"src": destination, "width": analyzed.drawing.width, "height": analyzed.drawing.height}],
            })
        updated["docs"] = [
            document for document in docs
            if not (isinstance(document, dict) and document.get("id") in owned_ids)
        ] + new_docs
        cccd_field = next(
            field for field in fields
            if isinstance(field, dict) and field.get("key") == "cccd"
        )
        sources = cccd_field.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError("CCCD sources are invalid")
        cccd_field["sources"] = [
            source for source in sources
            if not (isinstance(source, dict) and source.get("docId") in owned_ids)
        ]
        front = plan.candidate.front
        if front is None or front.ocr.number_bbox is None:
            raise ValueError("exact attachment requires located front")
        cccd_field["sources"].append({
            "docId": _owned_doc_id(plan.candidate.id, "front"), "page": 0,
            "value": front.ocr.cccd, "bbox": front.ocr.number_bbox,
            "confidence": front.ocr.cccd_confidence,
        })
        updated["checks"] = checklist.build_checklist(
            fields,
            {
                "matchedBy": packet.get("matchedBy", "no-roster"),
                "ocrIdentity": packet.get("ocrIdentity") or {"cccd": "", "name": ""},
                "rosterIdentity": packet.get("rosterIdentity"),
            },
            updated["docs"],
        )
        _atomic_json_write(manifest_path, updated)
        mapping["attachedPacketIndex"] = plan.target_packet_index
        try:
            _remove_stale_owned_files(old_owned_docs, packet_dir, new_paths)
        except OSError:
            pass
        return mapping
    except Exception:
        for path in created_files:
            if os.path.isfile(path):
                os.unlink(path)
        return _attachment_failure(plan)
