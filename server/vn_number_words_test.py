import pytest

from vn_number_words import parse_amount_words


class TestUnits:
    @pytest.mark.parametrize("text,expected", [
        ("không", 0),
        ("một", 1),
        ("hai", 2),
        ("ba", 3),
        ("bốn", 4),
        ("năm", 5),
        ("sáu", 6),
        ("bảy", 7),
        ("tám", 8),
        ("chín", 9),
    ])
    def test_each_digit(self, text, expected):
        assert parse_amount_words(text) == expected

    def test_tu_is_four(self):
        # "tư" replaces "bốn" after mươi: hai mươi tư = 24
        assert parse_amount_words("hai mươi tư") == 24

    def test_mot_is_one(self):
        # "mốt" replaces "một" after mươi: hai mươi mốt = 21
        assert parse_amount_words("hai mươi mốt") == 21


class TestTensAndHundreds:
    @pytest.mark.parametrize("text,expected", [
        ("mười", 10),
        ("mười một", 11),
        ("mười lăm", 15),
        ("hai mươi", 20),
        ("năm mươi sáu", 56),
        ("một trăm", 100),
        ("ba trăm lẻ năm", 305),
        ("ba trăm linh năm", 305),
        ("năm trăm năm mươi sáu", 556),
        ("chín trăm chín mươi chín", 999),
    ])
    def test_reads_the_group(self, text, expected):
        assert parse_amount_words(text) == expected

    def test_lam_is_five_after_muoi(self):
        assert parse_amount_words("hai mươi lăm") == 25


class TestScales:
    @pytest.mark.parametrize("text,expected", [
        ("một nghìn", 1_000),
        ("một ngàn", 1_000),
        ("mười nghìn", 10_000),
        ("ba trăm lẻ năm nghìn", 305_000),
        ("một triệu", 1_000_000),
        ("hai trăm bốn mươi triệu", 240_000_000),
        ("một tỷ", 1_000_000_000),
        ("một tỉ", 1_000_000_000),
    ])
    def test_applies_the_scale(self, text, expected):
        assert parse_amount_words(text) == expected

    def test_the_real_purchase_listing_total(self):
        """The words printed beside 240.305.556VNĐ on page 8 of the July
        submission — the independent read that corroborates the digits."""
        assert parse_amount_words(
            "hai trăm bốn mươi triệu ba trăm lẻ năm nghìn "
            "năm trăm năm mươi sáu đồng"
        ) == 240_305_556

    def test_a_billion_scale_amount(self):
        assert parse_amount_words(
            "hai tỷ ba trăm bốn mươi triệu năm nghìn sáu trăm"
        ) == 2_340_005_600


class TestSurvivesOcr:
    def test_missing_diacritics_still_read(self):
        # Tesseract drops and mangles tone marks constantly.
        assert parse_amount_words(
            "hai tram bon muoi trieu ba tram le nam nghin "
            "nam tram nam muoi sau dong"
        ) == 240_305_556

    def test_the_exact_ocr_output_from_page_eight(self):
        """`trắm` for `trăm` and `đông).` for `đồng)` — what Tesseract
        actually returned. Both survive accent folding."""
        assert parse_amount_words(
            "Hai trăm bốn mươi triệu ba trăm lẻ năm nghìn "
            "năm trắm năm mươi sáu đông)."
        ) == 240_305_556

    def test_currency_and_punctuation_are_ignored(self):
        assert parse_amount_words("(Một triệu đồng.)") == 1_000_000
        assert parse_amount_words("hai triệu VNĐ") == 2_000_000

    def test_case_is_irrelevant(self):
        assert parse_amount_words("HAI TRIỆU") == 2_000_000


class TestRefusesRatherThanGuesses:
    @pytest.mark.parametrize("text", [
        "",
        "   ",
        "đồng",
        "Người lập bảng kê",
        "Thái Thị Thảo Nguyên",
        "(Số tiền bằng chữ",
    ])
    def test_no_number_words_is_none(self, text):
        assert parse_amount_words(text) is None

    def test_a_lone_scale_word_is_not_an_amount(self):
        # "nghìn" alone carries no quantity; guessing 1000 would invent data.
        assert parse_amount_words("nghìn") is None
        assert parse_amount_words("triệu đồng") is None

    def test_stray_words_between_numbers_do_not_break_it(self):
        assert parse_amount_words("hai triệu và ba trăm nghìn") == 2_300_000
