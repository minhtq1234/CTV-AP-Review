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


def unplaceable(value):
    """A read the locator could not put anywhere on the page.

    This is what `semantic_read` hands over for a quote it could not find:
    `read_document` guarantees a value and a quote for every field it returns,
    and `locate_fields` keeps the field with `located=False` rather than
    dropping it, so the unlocatable rate stays measurable.

    Confidence 0.0 with the box, not beside it. `locate_fields` sets
    `located=False, exact=None` together, and `ocr_extract._semantic_fields`
    reads that as `0.0 if not field.located`, so production cannot emit
    bbox None at any other confidence. A fixture pairing None with 1.0 would
    green-light a combination the reader cannot produce -- and `_parts_cell`'s
    exactness guard reads confidence, so the pair has to stay faithful.
    """
    return {"docId": "contract-0", "page": 0, "value": value,
            "confidence": 0.0, "bbox": None}


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


def test_a_value_the_locator_could_not_place_is_not_present():
    """The bug this module shipped with. `semantic_read.read_document`
    guarantees every field it returns has a truthy value and a quote, so
    accepting a value as presence made the box irrelevant for every LLM read
    and let three bank details be declared "on the document" on the model's
    word alone."""
    labels = cr.BY_STT[8].params["part_labels"]
    result = check_parts(BANK, {
        "bank": unplaceable("Techcombank"),
        "branch": source("Tân Bình"),
        "province": source("TP.HCM"),
    }, labels=labels)

    assert result.coverage is PartsCoverage.PARTIAL
    assert result.unlocatable == ("bank",)
    assert "bank" in result.missing
    assert "Có đủ" not in result.note
    assert "chưa chỉ được vị trí" in result.note


def test_an_unplaceable_claim_is_kept_not_dropped():
    """Three claims, three different sentences. Dropping the unplaceable reads
    would destroy the measurement `locate_fields` keeps them for; calling them
    absent would state an absence nobody observed."""
    read = check_parts(BANK, {part: unplaceable("Techcombank")
                              for part in BANK})
    looked = check_parts(BANK, {})
    did_not = check_parts(BANK, None)

    assert read.coverage is PartsCoverage.NONE
    assert read.unlocatable == BANK
    assert read.missing == BANK
    assert read.note != looked.note
    assert read.note != did_not.note


def test_nothing_located_does_not_mean_nothing_was_read():
    """The note may not refute itself one sentence later.

    "Không thấy nội dung nào trên chứng từ" is a claim about the whole
    document, and it was reached off `found` alone -- so with nothing located
    and one part read-but-unplaceable the note said no content at all was
    seen, then named a part it had read. `found` stopped being the right test
    the moment an unplaceable read became its own bucket.
    """
    labels = cr.BY_STT[8].params["part_labels"]
    result = check_parts(BANK, {
        "bank": unplaceable("Techcombank"),
        "branch": source("", bbox=False),
        "province": source("", bbox=False),
    }, labels=labels)

    assert result.coverage is PartsCoverage.NONE
    assert result.found == ()
    assert result.unlocatable == ("bank",)
    # The whole-document claim is off the table: one part WAS read.
    assert "Không thấy nội dung nào" not in result.note
    assert "Chưa thấy trên chứng từ: Chi nhánh, Tỉnh/TP." in result.note
    assert "Đọc được nhưng chưa chỉ được vị trí trên trang: Tên ngân hàng." \
        in result.note


def test_nothing_read_at_all_still_says_so_plainly():
    """The other side of the guard above: with no bucket to contradict it, the
    whole-document sentence is the honest one and must not be softened away."""
    result = check_parts(BANK, {part: source("", bbox=False) for part in BANK})

    assert result.coverage is PartsCoverage.NONE
    assert result.unlocatable == ()
    assert "Không thấy nội dung nào trên chứng từ" in result.note


def test_absent_and_unplaceable_are_two_different_sentences():
    """A part nobody found and a part read but unplaceable are different facts
    about different parts, and folding them into one list tells the reviewer to
    go looking for a clause that was already read to them."""
    labels = cr.BY_STT[8].params["part_labels"]
    result = check_parts(BANK, {
        "bank": source("Techcombank"),
        "branch": unplaceable("Tân Bình"),
    }, labels=labels)

    assert "Chưa thấy trên chứng từ" in result.note
    assert "Đọc được nhưng chưa chỉ được vị trí trên trang" in result.note

    absent, unplaced = result.note.split("Đọc được")
    assert "Tỉnh/TP" in absent and "Chi nhánh" not in absent
    assert "Chi nhánh" in unplaced and "Tỉnh/TP" not in unplaced
