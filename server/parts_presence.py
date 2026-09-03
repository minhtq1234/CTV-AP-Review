"""Which of a criterion's declared parts are present on a document.

Presence, not agreement. #8's own text is `Kiểm tra có đủ 3 nội dung: Tên ngân
hàng – Chi nhánh – Tỉnh/TP` -- is the content there. There is nothing to compare
it against: the bảng kê has a bank column and none for branch or province
(`roster_checks._HEADER_PATTERNS`), and #13 has no Excel document at all
(`criteria.py`'s docs for it are contract/appendix/BBNT). A comparison-shaped
answer here would have to invent the reference side.

`parts=` has been declared on these criteria since they were written and read by
nothing. This reads it.

Pure: no PDF, no Tesseract, no key, no manifest. It takes what a reader found and
says which declared parts that covers, so it is testable today and stays correct
once a real reader exists.
"""
from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass


class PartsCoverage(enum.Enum):
    """How much of what a criterion declares was found on the document.

    No `MISMATCH`. Under presence nothing disagrees -- there is no counterparty
    -- and a verdict that cannot occur is an invitation to reintroduce the
    comparison this deliberately does not do.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True)
class PartsPresence:
    coverage: PartsCoverage
    #: Declared order, not discovery order: it is the order the criterion's own
    #: text lists them in, which is the order a reviewer reads the document.
    found: tuple[str, ...]
    missing: tuple[str, ...]
    #: Under presence the note is the entire answer a person acts on, so it is
    #: written in their words rather than in part keys.
    note: str


def located_or_read(part: str, read: Mapping | None) -> bool:
    """Whether a reader put this part somewhere on the document.

    A readable value is obviously present. So is a located-but-unread hit:
    `ocr_extract.locate_field` already emits `{"value": "", "bbox": ...}` when it
    found the content and could not read it, and for "is it there?" that is a
    yes.

    The size guard is load-bearing. `ocr_extract._EMPTY_SOURCE` is the
    placeholder written when a field's label appears in no document at all --
    empty value, zero-size box. Without the guard it reads as present and every
    criterion silently passes.
    """
    if not read:
        return False
    if str(read.get("value") or "").strip():
        return True
    bbox = read.get("bbox") or {}
    return bool(bbox.get("width")) and bool(bbox.get("height"))


def check_parts(
    parts: tuple[str, ...],
    reads: Mapping[str, Mapping] | None,
    *,
    labels: Mapping[str, str] | None = None,
    is_present: Callable[[str, Mapping | None], bool] = located_or_read,
) -> PartsPresence:
    """Which of `parts` a reader covered.

    `reads is None` means no reader covering these parts ran; an empty mapping
    means one ran and found none of them. Those are different claims and this
    keeps them apart -- collapsing them would turn "we did not look" into "no",
    which is the one direction this engine refuses.

    Anything in `reads` that `parts` does not declare is ignored: a reader
    returning more than it was asked for must not make a criterion complete on
    the strength of something the criterion never asked about.
    """
    if reads is None:
        return PartsPresence(
            PartsCoverage.NONE, (), (),
            "Chưa có bước đọc nào kiểm tra các nội dung này trên chứng từ.",
        )

    found = tuple(part for part in parts if is_present(part, reads.get(part)))
    missing = tuple(part for part in parts if part not in found)

    if not found:
        return PartsPresence(
            PartsCoverage.NONE, (), missing,
            f"Không thấy nội dung nào trên chứng từ: {_names(missing, labels)}.",
        )
    if not missing:
        return PartsPresence(
            PartsCoverage.COMPLETE, found, (),
            f"Có đủ {len(found)} nội dung trên chứng từ.",
        )
    return PartsPresence(
        PartsCoverage.PARTIAL, found, missing,
        f"Chưa thấy trên chứng từ: {_names(missing, labels)}.",
    )


def _names(parts: tuple[str, ...], labels: Mapping[str, str] | None) -> str:
    """The reviewer's words for these parts, falling back to the key itself."""
    return ", ".join((labels or {}).get(part, part) for part in parts)
