"""Derive response-only packet-boundary review evidence.

The assessment is intentionally pure: it reads stored packet metadata and a
manifest, but never rewrites page ranges or persists display state.
"""
from __future__ import annotations

import os
import re


_BLOCKING_FLAGS = ("length-out-of-range", "near-threshold", "auto-merged")
_PAGE_FILE = re.compile(r"^pg(\d+)\.(?:png|jpe?g)$", re.IGNORECASE)


def _contract_starts(packet: dict, manifest: dict | None) -> list[int]:
    if not isinstance(manifest, dict):
        return []
    packet_pages = packet.get("pages") or []
    if len(packet_pages) < 2:
        return []
    packet_start, packet_end = packet_pages[0], packet_pages[1]
    if (
        type(packet_start) is not int
        or type(packet_end) is not int
        or packet_end < packet_start
    ):
        return []
    docs = manifest.get("docs")
    if not isinstance(docs, list):
        return []
    starts = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "contract":
            continue
        pages = doc.get("pages")
        if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
            continue
        page_name = os.path.basename(str(pages[0].get("src") or ""))
        match = _PAGE_FILE.match(page_name)
        if match:
            absolute_page = packet_start + int(match.group(1))
            if packet_start <= absolute_page <= packet_end:
                starts.append(absolute_page)
    return sorted(set(starts))


def assess_packet_boundary(
    packet: dict,
    manifest: dict | None,
    case_summary: dict | None,
    resolution: dict | None = None,
) -> dict:
    flags = set(packet.get("flags") or [])
    reasons = [flag for flag in _BLOCKING_FLAGS if flag in flags]
    starts = _contract_starts(packet, manifest)
    suspected_multiple = len(starts) >= 2
    if suspected_multiple:
        reasons.append("multiple-contract-starts")

    summary = case_summary or {}
    roster_n = summary.get("roster_n")
    if reasons and roster_n is not None and summary.get("found") != roster_n:
        reasons.append("batch-count-mismatch")

    return {
        "status": (
            "accepted"
            if reasons and (resolution or {}).get("action") == "keep-current"
            else "review" if reasons else "clear"
        ),
        "suspectedMultiplePackets": suspected_multiple,
        "reasons": reasons,
        "candidateStarts": starts,
    }


def assess_case_boundaries(case: dict, manifests: dict[int, dict]) -> dict:
    resolution = case.get("boundaryResolution")
    if resolution and resolution.get("action") == "keep-current":
        return {
            "status": "accepted",
            "packetIndexes": [],
            "reasons": resolution["reasons"],
        }

    reasons: list[str] = []
    packet_indexes: list[int] = []
    for packet in case.get("packets", []):
        assessment = assess_packet_boundary(
            packet,
            manifests.get(packet["index"]),
            case.get("summary"),
            resolution,
        )
        if assessment["status"] != "review":
            continue
        packet_indexes.append(packet["index"])
        for reason in assessment["reasons"]:
            if reason not in reasons:
                reasons.append(reason)
    return {
        "status": "review" if packet_indexes else "clear",
        "packetIndexes": packet_indexes,
        "reasons": reasons,
    }
