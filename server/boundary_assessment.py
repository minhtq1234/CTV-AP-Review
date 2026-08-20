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
    packet_start = int((packet.get("pages") or [0])[0])
    starts = []
    for doc in manifest.get("docs") or []:
        if not isinstance(doc, dict) or doc.get("kind") != "contract":
            continue
        pages = doc.get("pages") or []
        if not pages or not isinstance(pages[0], dict):
            continue
        page_name = os.path.basename(str(pages[0].get("src") or ""))
        match = _PAGE_FILE.match(page_name)
        if match:
            starts.append(packet_start + int(match.group(1)))
    return sorted(set(starts))


def assess_packet_boundary(
    packet: dict,
    manifest: dict | None,
    case_summary: dict | None,
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
        "status": "review" if reasons else "clear",
        "suspectedMultiplePackets": suspected_multiple,
        "reasons": reasons,
        "candidateStarts": starts,
    }
