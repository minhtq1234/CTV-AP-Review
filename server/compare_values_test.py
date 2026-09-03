import pytest

import compare_values as cv
from compare_values import Verdict


class TestPersonNames:
    def test_identical_matches(self):
        assert cv.compare("Đặng Hữu Lộc", "Đặng Hữu Lộc", "person") is Verdict.MATCH

    def test_a_tone_mark_difference_is_never_a_pass(self):
        """Tesseract drops Vietnamese diacritics routinely — but so does the
        difference between Anh and Ánh, who are two people."""
        assert cv.compare("Đặng Hữu Lộc", "Dang Huu Loc", "person") is Verdict.FUZZY
        assert cv.compare("Nguyễn Thị Ánh", "Nguyễn Thị Anh", "person") is Verdict.FUZZY

    def test_case_differences_fold(self):
        assert cv.compare("ĐẶNG HỮU LỘC", "Đặng Hữu Lộc", "person") is Verdict.FUZZY

    def test_a_different_word_count_is_a_mismatch_not_a_near_miss(self):
        # "Lê Thị Thu Hà" and "Lê Thị Thu Hà Vy" are two people however close
        # the strings are.
        assert cv.compare("Lê Thị Thu Hà", "Lê Thị Thu Hà Vy", "person") is Verdict.MISMATCH

    def test_a_one_letter_slip_within_the_same_word_count_is_fuzzy(self):
        assert cv.compare("Trần Văn Bảy", "Trần Văn Báy", "person") is Verdict.FUZZY

    def test_two_different_people_mismatch(self):
        assert cv.compare(
            "Đặng Hữu Lộc", "Vũ Thị Kim Ngân", "person",
        ) is Verdict.MISMATCH

    def test_an_empty_side_is_a_mismatch_not_a_match(self):
        assert cv.compare("Đặng Hữu Lộc", "", "person") is Verdict.MISMATCH
        assert cv.compare("", "Đặng Hữu Lộc", "person") is Verdict.MISMATCH


class TestOrganisationNames:
    def test_a_company_suffix_may_differ(self):
        assert cv.compare(
            "Công ty Cổ phần Tập đoàn VNG", "Tập đoàn VNG", "organisation",
        ) is Verdict.FUZZY

    def test_a_containment_match_is_still_not_an_automatic_pass(self):
        # The looser rule is for organisations only, and it stops at `fuzzy`.
        assert cv.compare("VNG Corporation", "VNG", "organisation") is Verdict.FUZZY

    def test_a_different_company_mismatches(self):
        assert cv.compare("Tập đoàn VNG", "Công ty Adtima", "organisation") is Verdict.MISMATCH

    def test_identical_still_matches_outright(self):
        assert cv.compare("Tập đoàn VNG", "Tập đoàn VNG", "organisation") is Verdict.MATCH


class TestIdentityNumbers:
    def test_identical_digits_match(self):
        assert cv.compare("001100000021", "001100000021", "digits") is Verdict.MATCH

    def test_punctuation_and_spaces_are_ignored(self):
        assert cv.compare("001100000021", "001 100 000 021", "digits") is Verdict.MATCH
        assert cv.compare("0011-0000-0021", "001100000021", "digits") is Verdict.MATCH

    def test_a_leading_zero_is_significant(self):
        """An ID is a string, not a quantity. Comparing these as integers would
        pass a bank account that has lost its leading zero."""
        assert cv.compare("001100000021", "01100000021", "digits") is Verdict.MISMATCH
        assert cv.compare("0022000000415", "22000000415", "digits") is Verdict.MISMATCH

    def test_one_wrong_digit_is_a_mismatch(self):
        # No fuzzy tier for identity numbers: a near miss is a different person.
        assert cv.compare("001100000021", "001100000029", "digits") is Verdict.MISMATCH

    def test_a_missing_side_is_a_mismatch(self):
        assert cv.compare("001100000021", "", "digits") is Verdict.MISMATCH
        assert cv.compare("001100000021", "không rõ", "digits") is Verdict.MISMATCH


class TestMoney:
    def test_formatting_is_ignored(self):
        assert cv.compare("7.777.778", "7777778", "money") is Verdict.MATCH
        assert cv.compare("7,777,778 đ", "7777778", "money") is Verdict.MATCH

    def test_a_leading_zero_is_not_significant(self):
        assert cv.compare("07777778", "7777778", "money") is Verdict.MATCH

    def test_a_different_amount_is_a_mismatch(self):
        assert cv.compare("7.777.778", "7.777.777", "money") is Verdict.MISMATCH

    def test_nothing_parseable_is_a_mismatch(self):
        assert cv.compare("7.777.778", "—", "money") is Verdict.MISMATCH


class TestDates:
    def test_the_same_day_in_two_formats(self):
        assert cv.compare("23/04/2003", "2003-04-23", "date") is Verdict.MATCH
        assert cv.compare("23/04/2003", "23-4-2003", "date") is Verdict.MATCH

    def test_a_leading_zero_does_not_matter(self):
        assert cv.compare("03/09/2003", "3/9/2003", "date") is Verdict.MATCH

    def test_a_different_day_is_a_mismatch(self):
        assert cv.compare("23/04/2003", "22/05/1989", "date") is Verdict.MISMATCH

    def test_an_unparseable_date_falls_back_to_the_literal(self):
        assert cv.compare("tháng 7/2026", "tháng 7/2026", "date") is Verdict.MATCH
        assert cv.compare("23/04/2003", "tháng 7", "date") is Verdict.MISMATCH


class TestEnum:
    def test_an_allowed_value_matches(self):
        assert cv.compare("Nam", "Nam", "enum", allowed=("Nam", "Nữ")) is Verdict.MATCH

    def test_folding_applies(self):
        assert cv.compare("Nữ", "Nu", "enum", allowed=("Nam", "Nữ")) is Verdict.FUZZY

    def test_a_value_outside_the_set_is_a_mismatch_even_if_both_sides_agree(self):
        # Acc's rule for #04 is that the value must be Nam or Nữ, not merely
        # that the documents agree with each other.
        assert cv.compare(
            "Khác", "Khác", "enum", allowed=("Nam", "Nữ"),
        ) is Verdict.MISMATCH

    def test_disagreement_within_the_set(self):
        assert cv.compare("Nam", "Nữ", "enum", allowed=("Nam", "Nữ")) is Verdict.MISMATCH


class TestConfidence:
    """`confidence` is `min(word confidence)` -- legibility, not correctness
    (docs/handoff-ver3.md) -- so it never decides a verdict here: an outright
    match is trusted at any confidence, a mismatch is never softened, and a
    fuzzy near miss already means "a person must look" independent of it.
    """

    def test_an_exact_match_passes_regardless_of_confidence(self):
        for confidence in (0.99, 0.7, 0.5, 0.02, 0.0):
            assert cv.compare(
                "001100000021", "001100000021", "digits", confidence=confidence,
            ) is Verdict.MATCH

    def test_an_exact_match_at_the_lowest_confidence_measured_is_a_clean_pass(self):
        # Packet 25, số tài khoản, July batch: an 11-digit read matching the
        # roster exactly, off a faint scan, at confidence 0.02. Before this was
        # fixed, that was downgraded to `low_conf` (-> `rv`) despite being right.
        assert cv.compare(
            "001100000021", "001100000021", "digits", confidence=0.02,
        ) is Verdict.MATCH

    def test_a_mismatch_stays_a_mismatch_however_unsure_the_read(self):
        # Downgrading a disagreement to "unsure" would hide it.
        assert cv.compare(
            "001100000021", "111111111111", "digits", confidence=0.1,
        ) is Verdict.MISMATCH

    def test_a_fuzzy_result_is_not_further_downgraded_by_confidence(self):
        # Fuzzy already means "a person must look"; there is no lower tier.
        assert cv.compare(
            "Đặng Hữu Lộc", "Dang Huu Loc", "person", confidence=0.1,
        ) is Verdict.FUZZY

    def test_no_confidence_supplied_is_fine(self):
        assert cv.compare(
            "001100000021", "001100000021", "digits", confidence=None,
        ) is Verdict.MATCH


class TestFormats:
    @pytest.mark.parametrize("value,ok", [
        ("001100000021", True),
        ("001 100 000 021", True),
        ("00110000002", False),      # 11 digits
        ("0011000000219", False),    # 13
        ("00110000002A", False),
        ("", False),
    ])
    def test_cccd_is_twelve_digits(self, value, ok):
        assert cv.matches_format(value, ("cccd12",)) is ok

    @pytest.mark.parametrize("value,ok", [
        ("C1234567", True),
        ("12345678", True),
        ("C123456", False),
        ("C12345678", False),
    ])
    def test_a_passport_is_eight_characters(self, value, ok):
        assert cv.matches_format(value, ("passport8",)) is ok

    def test_either_format_satisfies_a_pair(self):
        # #02 accepts a 12-digit CCCD or an 8-character passport.
        both = ("cccd12", "passport8")
        assert cv.matches_format("001100000021", both) is True
        assert cv.matches_format("C1234567", both) is True
        assert cv.matches_format("0792", both) is False

    @pytest.mark.parametrize("value,ok", [
        ("0303490096", True),        # 10
        ("001100000021", True),      # 12
        ("03034900", False),         # 8
        # The `-001` sub-unit form is 13 digits and belongs to a company
        # branch. #05 is "MST cá nhân": 10 or 12, per Acc's rule.
        ("0303490096-001", False),
    ])
    def test_mst_is_ten_or_twelve_digits(self, value, ok):
        assert cv.matches_format(value, ("mst10", "mst12")) is ok

    @pytest.mark.parametrize("value,ok", [
        ("23/04/2003", True),
        ("3/4/2003", True),
        ("2003-04-23", False),       # Acc requires dd/mm/yyyy text
        ("23/04/03", False),
        ("tháng 7", False),
    ])
    def test_the_date_format_acc_asks_for(self, value, ok):
        assert cv.matches_format(value, ("dd/mm/yyyy",)) is ok

    def test_no_format_rule_accepts_anything(self):
        assert cv.matches_format("whatever", ()) is True

    def test_an_unknown_format_name_is_refused_loudly(self):
        with pytest.raises(KeyError):
            cv.matches_format("x", ("not_a_format",))


class TestVerdictToStatus:
    def test_the_mapping_the_matrix_uses(self):
        from criteria import Status

        assert cv.to_status(Verdict.MATCH) is Status.OK
        assert cv.to_status(Verdict.MISMATCH) is Status.NO
        assert cv.to_status(Verdict.FUZZY) is Status.REVIEW

    def test_every_verdict_maps(self):
        for verdict in Verdict:
            assert cv.to_status(verdict) is not None


class TestWhyItIsFuzzy:
    """`fuzzy` has two causes and they are not the same finding. Reporting a
    near-miss as "only the tone marks differ" tells the reviewer something
    false."""

    def test_accent_folding_only(self):
        assert cv.fuzzy_reason("Đặng Hữu Lộc", "Dang Huu Loc", "person") == "folded"
        assert cv.fuzzy_reason("ĐẶNG HỮU LỘC", "Đặng Hữu Lộc", "person") == "folded"

    def test_a_genuinely_different_string_that_is_close(self):
        assert cv.fuzzy_reason("Trần Văn Bảy", "Trần Văn Bải", "person") == "near"

    def test_an_organisation_matched_by_containment(self):
        assert cv.fuzzy_reason(
            "Công ty Cổ phần Tập đoàn VNG", "Tập đoàn VNG", "organisation",
        ) == "near"

    def test_it_is_empty_when_the_verdict_is_not_fuzzy(self):
        assert cv.fuzzy_reason("A", "A", "person") == ""
        assert cv.fuzzy_reason("Đặng Hữu Lộc", "Mai Thanh Tùng", "person") == ""
