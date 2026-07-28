"""Deterministic, conservative front/back pairing for local CCCD images."""

from dataclasses import dataclass

from cccd_ocr import CccdImageOcr
from cccd_workbook import Anchor, EmbeddedDrawing


@dataclass(frozen=True)
class AnalyzedDrawing:
    drawing: EmbeddedDrawing
    ocr: CccdImageOcr


@dataclass(frozen=True)
class CardCandidate:
    id: str
    front: AnalyzedDrawing | None
    back: AnalyzedDrawing | None
    issues: tuple[str, ...]
    unknown: AnalyzedDrawing | None = None


def pair_drawings(images: list[AnalyzedDrawing]) -> list[CardCandidate]:
    if len({image.drawing.id for image in images}) != len(images):
        raise ValueError("duplicate drawing id")
    candidates = [
        candidate
        for component in _spatial_components(images)
        for candidate in _component_candidates(component)
    ]
    return sorted(candidates, key=lambda candidate: candidate.id)


def _spatial_components(
    images: list[AnalyzedDrawing],
) -> list[list[AnalyzedDrawing]]:
    ordered = sorted(images, key=lambda item: item.drawing.id)
    neighbours = {
        image.drawing.id: set()
        for image in ordered
    }
    by_id = {image.drawing.id: image for image in ordered}
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if _vertically_eligible(first, second):
                neighbours[first.drawing.id].add(second.drawing.id)
                neighbours[second.drawing.id].add(first.drawing.id)

    components = []
    visited = set()
    for image in ordered:
        if image.drawing.id in visited:
            continue
        pending = [image.drawing.id]
        component = []
        while pending:
            drawing_id = pending.pop()
            if drawing_id in visited:
                continue
            visited.add(drawing_id)
            component.append(by_id[drawing_id])
            pending.extend(sorted(
                neighbours[drawing_id] - visited,
                reverse=True,
            ))
        components.append(sorted(
            component,
            key=lambda item: item.drawing.id,
        ))
    return components


def _vertically_eligible(
    first: AnalyzedDrawing,
    second: AnalyzedDrawing,
) -> bool:
    first_anchor = first.drawing.anchor
    second_anchor = second.drawing.anchor
    if first_anchor.sheet != second_anchor.sheet:
        return False
    return (
        _vertical_overlap_ratio(first_anchor, second_anchor) >= .5
        or abs(first_anchor.from_row - second_anchor.from_row) <= 1
    )


def _component_candidates(
    component: list[AnalyzedDrawing],
) -> list[CardCandidate]:
    if len(component) != 2:
        issue = "ambiguous-pair" if len(component) > 2 else None
        return [_single_candidate(image, issue) for image in component]

    first, second = sorted(
        component,
        key=lambda image: (
            _horizontal_start(image),
            image.drawing.id,
        ),
    )
    if _horizontal_start(first) == _horizontal_start(second):
        return [
            _single_candidate(image, "ambiguous-pair")
            for image in component
        ]

    issues = (
        ("layout-side-conflict",)
        if first.ocr.side == "back" or second.ocr.side == "front"
        else ()
    )
    return [CardCandidate(
        id=f"card-{first.drawing.id}-{second.drawing.id}",
        front=first,
        back=second,
        issues=issues,
    )]


def _horizontal_start(image: AnalyzedDrawing) -> tuple[int, int]:
    anchor = image.drawing.anchor
    return anchor.from_col, anchor.from_col_offset


def _single_candidate(
    image: AnalyzedDrawing,
    issue: str | None = None,
) -> CardCandidate:
    if image.ocr.side == "front":
        return CardCandidate(
            f"card-{image.drawing.id}",
            image,
            None,
            (issue or "missing-back",),
        )
    if image.ocr.side == "back":
        return CardCandidate(
            f"card-{image.drawing.id}",
            None,
            image,
            (issue or "missing-front",),
        )
    return CardCandidate(
        f"card-{image.drawing.id}",
        None,
        None,
        (issue or "unknown-side",),
        image,
    )


def _vertical_overlap_ratio(first: Anchor, second: Anchor) -> float:
    first_height = first.to_row - first.from_row
    second_height = second.to_row - second.from_row
    if first_height <= 0 or second_height <= 0:
        return 0.0
    overlap = max(
        0,
        min(first.to_row, second.to_row)
        - max(first.from_row, second.from_row),
    )
    return overlap / min(first_height, second_height)
