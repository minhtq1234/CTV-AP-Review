"""Tests for confirming an expected value on a document.

The plan's tests, plus the ones the two mechanisms need to stay honest -- above
all that a number is confirmed only exactly, since a fuzzy number check would
confirm the very misreads it exists to name.
"""
from difflib import SequenceMatcher

from confirm_expected import MIN_NAME_RATIO, confirm_at_label, confirm_name


# --- confirm_name: the whole document ----------------------------------------

def test_the_expected_name_is_found_when_it_is_on_the_page():
    words = "HỢP ĐỒNG DỊCH VỤ Bà TRAN THI HAI Trưởng Phòng NGUYEN VAN MOT 01/01/1990".split()
    hit = confirm_name("NGUYEN VAN MOT", words)
    assert hit is not None
    assert hit.score >= 0.90


def test_another_persons_name_on_the_same_page_is_not_a_match():
    """The whole reason #01 refuses to answer today: a contract carries VNG's
    signatory as well as the contractor, and with no label saying which is
    which an extractor cannot choose. Confirming a SPECIFIC name is what makes
    this safe where discovering one is not -- the signatory being printed does
    not confirm the contractor, and a search for the contractor lands on the
    contractor's own occurrence, not the signatory's.

    NOTE: this is not the plan's version of this test. The plan asserted
    `confirm_name("TRAN THI HAI", ...) is None` on a page printing `Bà TRAN THI
    HAI` verbatim. No whole-document search can satisfy that -- the name is
    there, at 1.00 -- and it is not the invariant the plan's own measurements
    support. Those measured names against each other (79 distinct names, two
    different people never reaching 0.90), which is what is asserted here.
    """
    signatory_only = "HỢP ĐỒNG DỊCH VỤ Bà TRAN THI HAI Trưởng Phòng".split()
    assert confirm_name("NGUYEN VAN MOT", signatory_only) is None

    both = "HỢP ĐỒNG DỊCH VỤ Bà TRAN THI HAI Trưởng Phòng NGUYEN VAN MOT".split()
    hit = confirm_name("NGUYEN VAN MOT", both)
    assert hit is not None
    assert (hit.start, hit.end) == (10, 12), "landed on the signatory, not the contractor"


def test_two_people_sharing_a_surname_and_middle_name_do_not_collide():
    """Measured: the closest real pair on disk scores 0.80 -- two people
    sharing a surname and middle name, both in one submission. The threshold
    has to sit above that and below a real hit."""
    words = "Bên Cung Ứng NGUYEN VAN MOT ký tên".split()
    assert confirm_name("NGUYEN VAN HAI", words) is None


def test_accents_and_case_do_not_matter():
    """OCR drops diacritics routinely."""
    words = "ben cung ung NGUYEN VAN MOT".split()
    assert confirm_name("Nguyễn Văn Một", words) is not None


def test_a_missing_expected_value_confirms_nothing():
    """No roster match means nothing to search for. It must not fall back to
    'find any name', which is the discovery problem this avoids."""
    assert confirm_name("", "NGUYEN VAN MOT".split()) is None
    assert confirm_name("   ", "NGUYEN VAN MOT".split()) is None


def test_a_name_broken_across_the_page_words_still_confirms():
    """The words handed in are OCR tokens, not tidy ones: a name printed on a
    bare line arrives as separate boxes and sometimes with punctuation stuck to
    it."""
    words = "Bên Cung Ứng: NGUYEN VAN MOT, sinh năm 1990".split()
    assert confirm_name("NGUYEN VAN MOT", words) is not None


def test_word_boxes_are_accepted_as_well_as_strings():
    """Read time holds `{text,x,y,w,h}` word dicts; the span points back into
    them so a caller can box the hit."""
    words = [{"text": t, "x": i * 10, "y": 0, "w": 9, "h": 9, "conf": 0.9}
             for i, t in enumerate("ben cung ung NGUYEN VAN MOT".split())]
    hit = confirm_name("NGUYEN VAN MOT", words)
    assert hit is not None
    assert (hit.start, hit.end) == (3, 5)


def test_an_empty_page_confirms_nothing():
    assert confirm_name("NGUYEN VAN MOT", []) is None


# --- confirm_at_label: only where the label says ------------------------------

def test_an_mst_is_not_confirmed_by_the_cccd_printed_elsewhere():
    """Measured on 564 roster rows: cccd == mst in 100% of them, because a
    Vietnamese personal tax code IS the citizen's ID number. A free-floating
    search for the expected MST would match the CCCD occurrence and confirm
    itself -- which is why this one is anchored to its own label."""
    words = "CCCD số : 001100000001 ... MSTTNCN : 001100000009".split()
    assert confirm_at_label("001100000001", words, ("msttncn",)) is None


def test_the_value_at_the_label_is_confirmed():
    words = "CCCD số : 001100000001 ... MSTTNCN : 001100000009".split()
    hit = confirm_at_label("001100000009", words, ("msttncn",))
    assert hit is not None


def test_a_number_is_confirmed_only_exactly_never_fuzzily():
    """The safety property this whole mechanism rests on. One wrong digit in
    twelve scores 0.917 on SequenceMatcher -- ABOVE the 0.90 that is right for
    names. A fuzzy number check would 'confirm' precisely the one-digit
    misreads it exists to tell apart from a real disagreement, and would turn
    every near-miss into a downgraded finding."""
    assert SequenceMatcher(None, "001100000004", "001100000001").ratio() > MIN_NAME_RATIO

    words = "MSTTNCN : 001100000004".split()
    assert confirm_at_label("001100000001", words, ("msttncn",)) is None


def test_a_number_split_into_groups_by_ocr_still_confirms():
    """Tesseract routinely breaks a twelve-digit number into groups; the
    CCCD_SPACED pattern exists for the same reason."""
    words = "Số tài khoản : 1900 0000 01".split()
    assert confirm_at_label("1900000001", words, ("so tai khoan",)) is not None


def test_a_longer_number_at_the_label_is_a_different_number():
    """Rejoining groups must not let a run that merely contains the expected
    digits pass as them."""
    words = "Số tài khoản : 19000000019".split()
    assert confirm_at_label("1900000001", words, ("so tai khoan",)) is None


def test_a_label_that_is_not_on_the_page_confirms_nothing():
    words = "CCCD số : 001100000001".split()
    assert confirm_at_label("001100000001", words, ("msttncn",)) is None


def test_a_value_further_down_the_page_is_out_of_the_neighbourhood():
    """`only within the label's neighbourhood` is the point -- a match must be
    at the label, not merely after it."""
    filler = " ".join(["xxx"] * 20)
    words = f"MSTTNCN : không đọc được {filler} 001100000001".split()
    assert confirm_at_label("001100000001", words, ("msttncn",)) is None


def test_a_missing_expected_value_confirms_nothing_at_a_label():
    words = "MSTTNCN : 001100000009".split()
    assert confirm_at_label("", words, ("msttncn",)) is None


def test_a_multi_word_label_anchors_even_when_ocr_split_it():
    words = "Mã số thuế thu nhập cá nhân : 001100000009".split()
    hit = confirm_at_label("001100000009", words,
                           ("ma so thue thu nhap ca nhan",))
    assert hit is not None
