"""Build response-only packet-boundary proposals without exposing private evidence."""
from __future__ import annotations

from statistics import median

from boundary_assessment import assess_packet_boundary


_SIGNAL_ORDER = ("contract-title", "identity-change", "cadence", "visual")


def _median_packet_length(packets: list[dict]) -> float:
    lengths = []
    for packet in packets:
        pages = packet.get("pages") or []
        if len(pages) < 2:
            continue
        start, end = pages[0], pages[1]
        if type(start) is int and type(end) is int and end >= start:
            lengths.append(end - start + 1)
    return median(lengths) if lengths else 0


def _add_cadence_signals(candidates: dict[int, set[str]], median_length: float) -> None:
    if median_length <= 0:
        return
    ordered = sorted(candidates)
    tolerance = max(2, round(median_length * 0.5))
    for previous, page in zip(ordered, ordered[1:]):
        if abs((page - previous) - median_length) <= tolerance:
            candidates[page].add("cadence")


def _identity_evidence(manifests: dict, packets: list[dict]) -> list[tuple[int, str]]:
    records: list[tuple[int, str]] = []
    for packet in packets:
        manifest = manifests.get(packet.get("index"))
        if not isinstance(manifest, dict):
            continue
        evidence = manifest.get("boundaryEvidence")
        if not isinstance(evidence, list):
            continue
        for record in evidence:
            if not isinstance(record, dict):
                continue
            page = record.get("page")
            key = record.get("identityKey")
            if type(page) is not int or not isinstance(key, str) or not key.strip():
                continue
            records.append((page, key))
    return sorted(records, key=lambda record: record[0])


def _add_identity_change_signals(
    candidates: dict[int, set[str]], case: dict, manifests: dict
) -> None:
    previous_key: str | None = None
    for page, key in _identity_evidence(manifests, case.get("packets") or []):
        if previous_key is not None and key != previous_key:
            signals = candidates.get(page)
            if signals is not None and "contract-title" in signals:
                signals.add("identity-change")
        previous_key = key


def _packet_location(case: dict, page: int) -> dict:
    packet_locations = []
    for packet in case.get("packets") or []:
        pages = packet.get("pages") or []
        if len(pages) < 2:
            continue
        start, end = pages[0], pages[1]
        if type(start) is not int or type(end) is not int or not start <= page <= end:
            continue
        packet_locations.append((start, packet.get("index"), page - start))
    if not packet_locations:
        return {}
    _start, packet_index, relative_page = min(packet_locations)
    return {"packetIndex": packet_index, "relativePage": relative_page}


def _serialize_candidate(page: int, signals: set[str], location: dict) -> dict:
    ordered_signals = [signal for signal in _SIGNAL_ORDER if signal in signals]
    if "contract-title" in signals and (
        "identity-change" in signals or "cadence" in signals
    ):
        confidence = "high"
    elif "visual" in signals:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "page": page,
        "signals": ordered_signals,
        "confidence": confidence,
        **location,
    }


def build_boundary_proposal(case: dict, manifests: dict, total_pages: int) -> dict:
    """Fuse packet metadata into a deterministic, response-safe proposal."""
    del total_pages
    candidates: dict[int, set[str]] = {}
    affected: list[int] = []
    packets = case.get("packets") or []
    for packet in packets:
        start, _end = packet["pages"]
        candidates.setdefault(start, set()).add("visual")
        assessment = assess_packet_boundary(
            packet,
            manifests.get(packet["index"]),
            case.get("summary"),
        )
        for page in assessment["candidateStarts"]:
            candidates.setdefault(page, set()).add("contract-title")
        if assessment["status"] == "review":
            affected.append(packet["index"])
    _add_cadence_signals(candidates, _median_packet_length(packets))
    _add_identity_change_signals(candidates, case, manifests)
    starts = [
        _serialize_candidate(page, signals, _packet_location(case, page))
        for page, signals in sorted(candidates.items())
    ]
    return {
        "status": "review_required" if affected else "not_needed",
        "sourceCaseId": case["id"],
        "expectedPacketCount": (case.get("summary") or {}).get("roster_n"),
        "currentPacketCount": len(packets),
        "candidateStarts": starts,
        "affectedPacketIndexes": affected,
    }


def validate_revision_starts(
    starts, total_pages: int, first_packet_start: int
) -> tuple[int, ...]:
    if not starts or any(type(page) is not int for page in starts):
        raise ValueError("boundary-starts-invalid")
    if starts != sorted(set(starts)):
        raise ValueError("boundary-starts-invalid")
    if starts[0] != first_packet_start:
        raise ValueError("boundary-preamble-invalid")
    if starts[-1] >= total_pages or any(page < 0 for page in starts):
        raise ValueError("boundary-starts-out-of-range")
    return tuple(starts)
