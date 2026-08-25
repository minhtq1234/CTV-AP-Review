"""Build response-only packet-boundary proposals without exposing private evidence."""
from __future__ import annotations

from statistics import median

from boundary_assessment import assess_packet_boundary


_SIGNAL_ORDER = ("contract-title", "identity-change", "cadence", "visual")


def _valid_packet_range(packet: dict, total_pages: int) -> tuple[int, int, int] | None:
    packet_index = packet.get("index")
    pages = packet.get("pages") or []
    if type(packet_index) is not int or len(pages) < 2:
        return None
    start, end = pages[0], pages[1]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start <= end < total_pages
    ):
        return None
    return packet_index, start, end


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


def _packet_location(case: dict, page: int, total_pages: int) -> dict:
    packet_locations = []
    for packet in case.get("packets") or []:
        packet_range = _valid_packet_range(packet, total_pages)
        if packet_range is None:
            continue
        packet_index, start, end = packet_range
        if not start <= page <= end:
            continue
        packet_locations.append((start, packet_index, page - start))
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
    else:
        confidence = "medium"
    return {
        "page": page,
        "signals": ordered_signals,
        "confidence": confidence,
        **location,
    }


def build_boundary_proposal(case: dict, manifests: dict, total_pages: int) -> dict:
    """Fuse packet metadata into a deterministic, response-safe proposal."""
    candidates: dict[int, set[str]] = {}
    affected: list[int] = []
    affected_ranges: list[dict] = []
    packets = case.get("packets") or []
    for packet in packets:
        packet_range = _valid_packet_range(packet, total_pages)
        if packet_range is not None:
            packet_index, start, end = packet_range
            candidates.setdefault(start, set()).add("visual")
        assessment = assess_packet_boundary(
            packet,
            manifests.get(packet.get("index")),
            case.get("summary"),
        )
        if packet_range is not None:
            for page in assessment["candidateStarts"]:
                if start <= page <= end:
                    candidates.setdefault(page, set()).add("contract-title")
            if assessment["status"] == "review":
                affected.append(packet_index)
                affected_ranges.append({
                    "packetIndex": packet_index,
                    "startPage": start,
                    "endPage": end,
                })
    candidates = {
        page: signals
        for page, signals in candidates.items()
        if type(page) is int and 0 <= page < total_pages
    }
    _add_cadence_signals(candidates, _median_packet_length(packets))
    _add_identity_change_signals(candidates, case, manifests)
    starts = []
    for page, signals in sorted(candidates.items()):
        location = _packet_location(case, page, total_pages)
        if (
            type(location.get("packetIndex")) is not int
            or type(location.get("relativePage")) is not int
        ):
            continue
        starts.append(_serialize_candidate(page, signals, location))
    return {
        "status": "review_required" if affected else "not_needed",
        "sourceCaseId": case["id"],
        "expectedPacketCount": (case.get("summary") or {}).get("roster_n"),
        "currentPacketCount": len(packets),
        "candidateStarts": starts,
        "affectedPacketIndexes": affected,
        "affectedRanges": affected_ranges,
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
