"""Reviewer-driven card -> packet assignment for CCCD images OCR cannot match.

About half the cards in a real workbook never yield a readable number -- Excel
stores the pasted photos downscaled, so the printed digits land well under the
height Tesseract needs. Those cards stay `manual` no matter how the matcher is
tuned, and today the reviewer cannot even see that they exist.

This module lets a person say which packet a card belongs to. It deliberately
reuses the ingest's own attachment and reconciliation, so a manual assignment
produces byte-identical packet evidence to an automatic one; only `state` and
`matchMethod` differ, which is what keeps the provenance auditable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cccd_ingest import (
    PlannedMapping,
    attach_planned_mapping,
    reconcile_owned_evidence,
)
from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, CardCandidate
from cccd_workbook import Anchor, EmbeddedDrawing

# Sides a stored mapping can carry. "unknown" is a real card whose face the
# classifier could not name -- for attachment it is treated as the front,
# because a front is what a reviewer needs to read an identity off.
_SIDES = ("front", "back", "unknown")

_EXTENSION_BY_MEDIA_TYPE = {"image/png": "png", "image/jpeg": "jpg"}


class CccdManualError(Exception):
    """Assignment refused. `code` is safe to return to the client."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _Resolution:
    """Minimal stand-in for the resolver's verdict on a manual assignment."""

    state: str
    matched_by: str | None = "manual"


def _mappings(case: dict) -> list[dict]:
    workbook = case.get("cccdWorkbook")
    if not isinstance(workbook, dict):
        raise CccdManualError("no-cccd-workbook")
    mappings = workbook.get("mappings")
    if not isinstance(mappings, list):
        raise CccdManualError("no-cccd-workbook")
    return mappings


def _find(mappings: list[dict], card_id: str) -> dict:
    for mapping in mappings:
        if isinstance(mapping, dict) and mapping.get("candidateId") == card_id:
            return mapping
    raise CccdManualError("card-not-found")


def _sides_of(mapping: dict) -> list[tuple[str, dict]]:
    return [
        (side, mapping[side])
        for side in _SIDES
        if isinstance(mapping.get(side), dict)
    ]


def side_source_path(case_dir: str, mapping: dict, side: str) -> str:
    """Absolute path of one stored side, guaranteed to sit inside `case_dir`."""
    entry = mapping.get(side)
    if not isinstance(entry, dict):
        raise CccdManualError("side-not-found")
    relative = entry.get("sourcePath")
    if not isinstance(relative, str) or not relative:
        raise CccdManualError("side-not-found")
    resolved = os.path.realpath(os.path.join(case_dir, relative))
    root = os.path.realpath(case_dir)
    if os.path.commonpath([resolved, root]) != root:
        raise CccdManualError("side-not-found")
    if not os.path.isfile(resolved):
        raise CccdManualError("side-not-found")
    return resolved


def card_side_path(case: dict, case_dir: str, card_id: str, side: str) -> str:
    """Absolute path of `card_id`'s `side` image, for serving to the client."""
    if side not in _SIDES:
        raise CccdManualError("side-not-found")
    return side_source_path(case_dir, _find(_mappings(case), card_id), side)


def list_cards(case: dict) -> list[dict]:
    """Every card in the workbook, in workbook order.

    `attachedPacketIndex` is what lets the client tell the two populations
    apart: the picker offers the unattached ones, and a packet finds its own
    card by index so it can be detached again.

    Deliberately narrow: card id, image dimensions and whatever number OCR read
    (often empty -- that is the whole reason the card needs a human). No file
    paths, no roster values.
    """
    out = []
    for mapping in _mappings(case):
        if not isinstance(mapping, dict):
            continue
        identity = mapping.get("ocrIdentity") or {}
        out.append({
            "cardId": mapping.get("candidateId"),
            "state": mapping.get("state"),
            "attachedPacketIndex": mapping.get("attachedPacketIndex"),
            "number": identity.get("cccd") or "",
            "issues": list(mapping.get("issues") or []),
            "sides": [
                {
                    "side": side,
                    "width": entry.get("width"),
                    "height": entry.get("height"),
                }
                for side, entry in _sides_of(mapping)
            ],
        })
    return out


def _analyzed(entry: dict, case_dir: str) -> AnalyzedDrawing:
    """Rebuild the ingest's view of a stored side. Only the fields attachment
    actually reads are populated -- the OCR verdict is not re-derived here
    because a manual assignment does not rest on it."""
    anchor = entry.get("anchor") or {}
    drawing = EmbeddedDrawing(
        id=str(entry.get("drawingId") or ""),
        anchor=Anchor(
            str(anchor.get("sheet") or ""),
            int(anchor.get("fromRow") or 0),
            int(anchor.get("fromCol") or 0),
            int(anchor.get("toRow") or 0),
            int(anchor.get("toCol") or 0),
        ),
        media_type=str(entry.get("mediaType") or "image/png"),
        extension=_EXTENSION_BY_MEDIA_TYPE.get(
            str(entry.get("mediaType")), "png"
        ),
        width=int(entry.get("width") or 0),
        height=int(entry.get("height") or 0),
        sha256=str(entry.get("sha256") or ""),
        stored_path=os.path.join(case_dir, str(entry.get("sourcePath") or "")),
    )
    ocr = CccdImageOcr(
        side="unknown",
        side_confidence=0.0,
        cccd="",
        cccd_confidence=0.0,
        name="",
        name_confidence=0.0,
        number_bbox=None,
    )
    return AnalyzedDrawing(drawing=drawing, ocr=ocr)


def _plan(mapping: dict, case_dir: str, packet_index: int) -> PlannedMapping:
    """A PlannedMapping equivalent to what the ingest would have produced.

    An `unknown` side is promoted into the front slot: attachment only writes
    "front"/"back", and a card the classifier could not label is still the card
    the reviewer is pointing at.
    """
    working = dict(mapping)
    if not isinstance(working.get("front"), dict) and isinstance(
        working.get("unknown"), dict
    ):
        working["front"] = working["unknown"]
        working["unknown"] = None
    working["state"] = "assigned"
    working["matchMethod"] = "manual"
    front = working.get("front")
    back = working.get("back")
    if not isinstance(front, dict) and not isinstance(back, dict):
        raise CccdManualError("card-has-no-image")
    candidate = CardCandidate(
        id=str(mapping.get("candidateId") or ""),
        front=_analyzed(front, case_dir) if isinstance(front, dict) else None,
        back=_analyzed(back, case_dir) if isinstance(back, dict) else None,
        issues=tuple(working.get("issues") or ()),
    )
    return PlannedMapping(
        candidate=candidate,
        resolution=_Resolution("assigned"),
        target_packet_index=packet_index,
        mapping=working,
    )


def _detached(mapping: dict) -> dict:
    out = dict(mapping)
    out["attachedPacketIndex"] = None
    out["state"] = "manual"
    out["matchMethod"] = None
    for side in _SIDES:
        if isinstance(out.get(side), dict):
            entry = dict(out[side])
            entry["packetPath"] = None
            out[side] = entry
    return out


def _summary(mappings: list[dict]) -> dict:
    attached = sum(
        1
        for mapping in mappings
        if isinstance(mapping, dict)
        and mapping.get("attachedPacketIndex") is not None
    )
    return {
        "candidates": len(mappings),
        "attached": attached,
        "unresolved": len(mappings) - attached,
    }


def assign_card(
    case: dict,
    card_id: str,
    packet_index: int | None,
    case_dir: str,
    manifest_paths: dict[int, str],
) -> dict:
    """Attach `card_id` to `packet_index`, or detach it when that is None.

    Reconciliation runs either way, so a card moved between packets leaves no
    evidence behind in the packet it came from.
    """
    mappings = _mappings(case)
    mapping = _find(mappings, card_id)
    position = mappings.index(mapping)

    if packet_index is not None:
        if (
            not isinstance(packet_index, int)
            or isinstance(packet_index, bool)
            or packet_index not in manifest_paths
        ):
            raise CccdManualError("unknown-packet")
        taken = next(
            (
                other
                for other in mappings
                if isinstance(other, dict)
                and other is not mapping
                and other.get("attachedPacketIndex") == packet_index
            ),
            None,
        )
        if taken is not None:
            raise CccdManualError("packet-already-has-card")

    # Detach first so a move frees the old packet before the new one is written.
    mappings[position] = _detached(mapping)
    if not reconcile_owned_evidence(manifest_paths, case_dir, mappings):
        raise CccdManualError("reconcile-failed")

    if packet_index is not None:
        plan = _plan(mappings[position], case_dir, packet_index)
        packet = next(
            (
                p
                for p in case.get("packets") or []
                if isinstance(p, dict) and p.get("index") == packet_index
            ),
            None,
        )
        if packet is None:
            raise CccdManualError("unknown-packet")
        result = attach_planned_mapping(
            plan,
            packet,
            manifest_paths[packet_index],
            case_dir,
        )
        if result.get("attachedPacketIndex") != packet_index:
            raise CccdManualError("attach-failed")
        mappings[position] = result

    case["cccdWorkbook"]["mappings"] = mappings
    case["cccdWorkbook"]["summary"] = _summary(mappings)
    return case
