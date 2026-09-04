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
    #: The parts a reader read and could not place on the page. A named subset
    #: of `missing`, never of `found`: a value with nothing to check it against
    #: is not presence. `found` + `missing` still partition `parts`, so nothing
    #: is dropped and the unlocatable rate `semantic_read.locate_fields` gives
    #: up dropping quotes to preserve stays countable off this answer.
    unlocatable: tuple[str, ...] = ()


def located_on_page(part: str, read: Mapping | None) -> bool:
    """Whether a reader could point at this part on the document.

    A positioned box, and nothing less. A truthy value alone is NOT presence:
    `semantic_read.read_document` guarantees every field it returns has a value
    and a quote, so accepting a value would make this predicate constant-true
    for every LLM read and turn "the model asserted it" into "it is on the
    page". `locate_fields` deliberately keeps a quote it could not place with
    `located=False`, and this is the flag consulting it.

    A located-but-unread hit still counts: `ocr_extract.locate_field` emits
    `{"value": "", "bbox": ...}` when it found the content and could not read
    it, and for "is it there?" that is a yes.

    The size guard is load-bearing. `ocr_extract._EMPTY_SOURCE` is the
    placeholder written when a field's label appears in no document at all --
    empty value, zero-size box. Without the guard it reads as present and every
    criterion silently passes.
    """
    if not read:
        return False
    bbox = read.get("bbox") or {}
    return bool(bbox.get("width")) and bool(bbox.get("height"))


def claimed_without_place(part: str, read: Mapping | None) -> bool:
    """Whether a reader produced a value for this part with nowhere to point.

    The third answer. Counting such a part as found is the model asserting its
    own correctness; counting it as plainly absent states an absence nobody
    observed -- a reader did read that clause, it just could not be placed.
    Both are guesses, so it gets named instead of guessed at.
    """
    if not read:
        return False
    return (bool(str(read.get("value") or "").strip())
            and not located_on_page(part, read))


def check_parts(
    parts: tuple[str, ...],
    reads: Mapping[str, Mapping] | None,
    *,
    labels: Mapping[str, str] | None = None,
    is_present: Callable[[str, Mapping | None], bool] = located_on_page,
    is_claimed: Callable[[str, Mapping | None], bool] = claimed_without_place,
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
    unlocatable = tuple(part for part in missing
                        if is_claimed(part, reads.get(part)))
    absent = tuple(part for part in missing if part not in unlocatable)

    if not missing:
        return PartsPresence(
            PartsCoverage.COMPLETE, found, (),
            f"Có đủ {len(found)} nội dung trên chứng từ.",
        )

    coverage = PartsCoverage.PARTIAL if found else PartsCoverage.NONE
    return PartsPresence(
        coverage, found, missing,
        _note(found, absent, unlocatable, labels),
        unlocatable,
    )


def _note(
    found: tuple[str, ...],
    absent: tuple[str, ...],
    unlocatable: tuple[str, ...],
    labels: Mapping[str, str] | None,
) -> str:
    """One sentence per bucket, never one sentence for two of them.

    "Not on the document" and "read but unplaceable" are different claims about
    different parts, and folding the second into the first is the same lie as
    counting it present, pointed the other way.

    The "nào" wording -- "no content at all on the document" -- is a claim
    about the whole document, so it is only available when neither other
    bucket contradicts it. `found` alone is the wrong test now that a read the
    locator could not place is its own bucket: with nothing located and one
    part read-but-unplaceable it produced "Không thấy nội dung nào trên chứng
    từ: Chi nhánh, Tỉnh/TP. Đọc được nhưng chưa chỉ được vị trí trên trang:
    Tên ngân hàng." -- a sentence its own next sentence refutes, in the note
    that is the entire answer a reviewer acts on.
    """
    sentences = []
    if absent:
        sentences.append(
            f"Chưa thấy trên chứng từ: {_names(absent, labels)}."
            if found or unlocatable
            else f"Không thấy nội dung nào trên chứng từ: {_names(absent, labels)}."
        )
    if unlocatable:
        sentences.append("Đọc được nhưng chưa chỉ được vị trí trên trang: "
                         f"{_names(unlocatable, labels)}.")
    return " ".join(sentences)


def _names(parts: tuple[str, ...], labels: Mapping[str, str] | None) -> str:
    """The reviewer's words for these parts, falling back to the key itself."""
    return ", ".join((labels or {}).get(part, part) for part in parts)
