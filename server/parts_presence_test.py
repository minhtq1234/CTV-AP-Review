"""Which of a criterion's declared parts are present on a document.

Presence, not agreement: #8 asks "Kiểm tra có đủ 3 nội dung", which is whether
the content is there -- there is no reference to agree with. The bảng kê has no
branch or province column, and #13 has no Excel document at all.
"""
import criteria as cr
from parts_presence import PartsCoverage, check_parts


def source(value, *, bbox=True):
    """One reader hit, in the shape `ocr_extract.extract_fields` already emits."""
    return {"docId": "contract-0", "page": 0, "value": value, "confidence": 0.95,
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 30} if bbox
            else {"x": 0, "y": 0, "width": 0, "height": 0}}


BANK = ("bank", "branch", "province")


def test_every_declared_part_found_is_complete():
    result = check_parts(BANK, {
        "bank": source("Techcombank"),
        "branch": source("Tân Bình"),
        "province": source("TP.HCM"),
    })

    assert result.coverage is PartsCoverage.COMPLETE
    assert result.missing == ()
    assert result.found == BANK


def test_a_part_not_found_is_named_not_counted():
    """"Two of three" sends nobody anywhere. Which two decides where to look."""
    result = check_parts(BANK, {"bank": source("Techcombank")})

    assert result.coverage is PartsCoverage.PARTIAL
    assert result.missing == ("branch", "province")
    assert result.found == ("bank",)


def test_a_located_but_unread_part_counts_as_present():
    """The semantic core. `ocr_extract.locate_field` already emits a hit with
    `value=""` and a real bbox when it found the content but could not read it
    (ocr_extract.py:647-648). For a presence question that is a yes."""
    result = check_parts(BANK, {
        "bank": source("Techcombank"),
        "branch": source(""),
        "province": source(""),
    })

    assert result.coverage is PartsCoverage.COMPLETE
    assert result.found == BANK


def test_the_empty_placeholder_source_is_not_present():
    """`ocr_extract._EMPTY_SOURCE` is the placeholder written when a field's
    label appears in no document at all: an empty value AND a zero-size box.
    Without the size guard it reads as present and every criterion passes."""
    result = check_parts(BANK, {
        "bank": source("Techcombank"),
        "branch": source("", bbox=False),
        "province": source("", bbox=False),
    })

    assert result.coverage is PartsCoverage.PARTIAL
    assert result.missing == ("branch", "province")


def test_no_reader_is_none_and_names_itself_that_way():
    """Nobody looked. Not the same claim as looked-and-found-nothing, and this
    engine refuses to turn "we could not see" into "no"."""
    result = check_parts(BANK, None)

    assert result.coverage is PartsCoverage.NONE
    assert result.missing == ()
    assert "chưa" in result.note.lower() or "không đọc" in result.note.lower()


def test_a_reader_that_found_nothing_is_none_with_a_different_note():
    """Looked and saw none of them. Same coverage, different sentence -- the two
    must never be indistinguishable to a reviewer."""
    looked = check_parts(BANK, {})
    did_not = check_parts(BANK, None)

    assert looked.coverage is PartsCoverage.NONE
    assert looked.missing == BANK
    assert looked.note != did_not.note


def test_the_note_names_the_missing_parts_in_the_reviewers_words():
    """Under presence the note is the whole answer, so it must not put an
    internal key in front of a person."""
    labels = cr.BY_STT[8].params["part_labels"]
    result = check_parts(BANK, {"bank": source("Techcombank")}, labels=labels)

    assert "Chi nhánh" in result.note
    assert "Tỉnh/TP" in result.note
    assert "branch" not in result.note
    assert "province" not in result.note


def test_the_presence_test_is_injectable():
    """Task 5's reader will decide presence differently. The default has to be
    replaceable without reaching into this module."""
    seen = []

    def record(part, read):
        seen.append(part)
        return True

    result = check_parts(BANK, {"bank": source("x")}, is_present=record)

    assert seen == list(BANK), "called once per declared part, in order"
    assert result.coverage is PartsCoverage.COMPLETE


def test_a_part_nobody_declared_is_ignored():
    """A reader returning more than it was asked for must not make a criterion
    complete on the strength of something the criterion never declared."""
    result = check_parts(BANK, {
        "bank": source("Techcombank"),
        "swift": source("TCBVVNVX"),
    })

    assert result.coverage is PartsCoverage.PARTIAL
    assert "swift" not in result.found
    assert result.found == ("bank",)


def test_found_and_missing_keep_the_declared_order():
    """Declared order is the order the criterion's own text lists them in, which
    is the order a reviewer reads down the document."""
    parts = ("amount_basis", "term", "term_start", "method", "account")
    result = check_parts(parts, {
        "term": source("30 ngày"),
        "account": source("1900000001"),
        "amount_basis": source("8.000.000"),
    })

    assert result.found == ("amount_basis", "term", "account")
    assert result.missing == ("term_start", "method")
