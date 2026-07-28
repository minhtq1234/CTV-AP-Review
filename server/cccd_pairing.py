"""Deterministic, conservative front/back pairing for local CCCD images."""

from dataclasses import dataclass
from math import hypot

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
    ordered = sorted(images, key=lambda image: image.drawing.id)
    fronts = [image for image in ordered if image.ocr.side == "front"]
    backs = [image for image in ordered if image.ocr.side == "back"]
    eligible_backs = {
        front.drawing.id: _eligible_opposites(front, backs)
        for front in fronts
    }
    eligible_fronts = {
        back.drawing.id: _eligible_opposites(back, fronts)
        for back in backs
    }
    paired_ids: set[str] = set()
    pairs: list[tuple[AnalyzedDrawing, AnalyzedDrawing]] = []

    for front in fronts:
        choices = eligible_backs[front.drawing.id]
        if not choices:
            continue
        back = choices[0][1]
        reverse_choices = eligible_fronts[back.drawing.id]
        if (
            reverse_choices
            and reverse_choices[0][1].drawing.id == front.drawing.id
            and _has_margin(
                choices[0][0],
                [distance for distance, _ in choices[1:]],
            )
            and _has_margin(
                reverse_choices[0][0],
                [distance for distance, _ in reverse_choices[1:]],
            )
            and front.drawing.id not in paired_ids
            and back.drawing.id not in paired_ids
        ):
            pairs.append((front, back))
            paired_ids.update((front.drawing.id, back.drawing.id))

    candidates = [
        CardCandidate(
            id=f"card-{front.drawing.id}-{back.drawing.id}",
            front=front,
            back=back,
            issues=(),
        )
        for front, back in pairs
    ]
    candidates.extend(
        _unpaired_candidate(image, eligible_backs, eligible_fronts)
        for image in ordered
        if image.drawing.id not in paired_ids
    )
    return sorted(candidates, key=lambda candidate: candidate.id)


def _unpaired_candidate(
    image: AnalyzedDrawing,
    eligible_backs: dict[str, list[tuple[float, AnalyzedDrawing]]],
    eligible_fronts: dict[str, list[tuple[float, AnalyzedDrawing]]],
) -> CardCandidate:
    if image.ocr.side == "front":
        issue = (
            "ambiguous-pair"
            if eligible_backs[image.drawing.id]
            else "missing-back"
        )
        return CardCandidate(f"card-{image.drawing.id}", image, None, (issue,))
    if image.ocr.side == "back":
        issue = (
            "ambiguous-pair"
            if eligible_fronts[image.drawing.id]
            else "missing-front"
        )
        return CardCandidate(f"card-{image.drawing.id}", None, image, (issue,))
    return CardCandidate(
        f"card-{image.drawing.id}",
        None,
        None,
        ("unknown-side",),
        image,
    )


def _eligible_opposites(
    source: AnalyzedDrawing,
    candidates: list[AnalyzedDrawing],
) -> list[tuple[float, AnalyzedDrawing]]:
    return sorted(
        (
            (
                _anchor_center_distance(
                    source.drawing.anchor,
                    candidate.drawing.anchor,
                ),
                candidate,
            )
            for candidate in candidates
            if _eligible(source, candidate)
        ),
        key=lambda item: (item[0], item[1].drawing.id),
    )


def _eligible(first: AnalyzedDrawing, second: AnalyzedDrawing) -> bool:
    first_anchor = first.drawing.anchor
    second_anchor = second.drawing.anchor
    if first_anchor.sheet != second_anchor.sheet:
        return False
    overlap = _vertical_overlap_ratio(first_anchor, second_anchor)
    row_delta = abs(first_anchor.from_row - second_anchor.from_row)
    return overlap >= .5 or row_delta <= 1


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


def _anchor_center_distance(first: Anchor, second: Anchor) -> float:
    first_row_center = (first.from_row + first.to_row) / 2
    second_row_center = (second.from_row + second.to_row) / 2
    first_col_center = (first.from_col + first.to_col) / 2
    second_col_center = (second.from_col + second.to_col) / 2
    row_scale = max(
        1.0,
        (
            (first.to_row - first.from_row)
            + (second.to_row - second.from_row)
        ) / 2,
    )
    col_scale = max(
        1.0,
        (
            (first.to_col - first.from_col)
            + (second.to_col - second.from_col)
        ) / 2,
    )
    return hypot(
        (first_row_center - second_row_center) / row_scale,
        (first_col_center - second_col_center) / col_scale,
    )


def _has_margin(best: float, alternatives: list[float]) -> bool:
    return (
        not alternatives
        or (
            best < min(alternatives)
            and best <= min(alternatives) * .8
        )
    )
