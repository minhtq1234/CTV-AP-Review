import purchase_listing as pl


def w(text, x, y, width, height, conf):
    return {"text": text, "x": x, "y": y, "w": width, "h": height,
            "conf": float(conf)}


def word(text, x, y, conf=96.0):
    return w(text, x, y, len(text) * 20, 30, conf)


def line(text, y, x0=280, conf=96.0):
    """One OCR line, words laid out left to right like the real page."""
    out, x = [], x0
    for token in text.split():
        out.append(word(token, x, y, conf))
        x += len(token) * 20 + 20
    return out


#: Page 8 of the July submission, verbatim as Tesseract read it — every
#: coordinate, width and confidence exactly as returned. Only the preparer's
#: name is substituted, since that is real PII; the geometry is what this
#: parser reads and none of it is changed.
#:
#: Reproduced faithfully on purpose. A hand-written version of this page had
#: every word of one wrapped cell on a single y, which merged a stray table
#: rule into the total line and made a broken parser look correct. The real
#: page spans y=281..302 for that line, so the rule at y=311 falls outside it.
REAL_PAGE_8 = [
    w('Hồ', 751, 134, 49, 38, 48),
    w('Chí', 814, 142, 57, 30, 96),
    w('Minh', 766, 191, 90, 29, 96),
    w('bốn', 1934, 281, 69, 42, 96),
    w('(Số', 1402, 282, 61, 51, 95),
    w('tiền', 1476, 282, 69, 42, 96),
    w('bằng', 1557, 282, 87, 51, 96),
    w('Tổng', 297, 283, 95, 50, 96),
    w('chữ', 1657, 290, 67, 34, 93),
    w('mươi', 2014, 290, 96, 33, 96),
    w('triệu', 2122, 290, 83, 39, 96),
    w('Hai', 1761, 291, 64, 32, 96),
    w('giá', 406, 292, 51, 41, 96),
    w('trị', 472, 292, 36, 39, 96),
    w('hàng', 524, 292, 87, 41, 96),
    w('hóa,', 624, 292, 75, 38, 96),
    w('dịch', 714, 292, 77, 39, 96),
    w('vào:', 952, 292, 74, 32, 92),
    w('240.305.556VNĐ', 1054, 292, 323, 32, 92),
    w('trăm', 1840, 293, 82, 30, 96),
    w(':', 1740, 301, 5, 23, 93),
    w('vụ', 803, 302, 43, 29, 96),
    w('mua', 861, 302, 78, 22, 96),
    w('-', 272, 311, 12, 4, 93),          # a table rule read as a word
    w('đông).', 1129, 345, 113, 42, 95),  # `đồng)` — OCR lost the tone mark
    w('ba', 273, 346, 39, 32, 96),
    w('lẻ', 421, 346, 29, 32, 96),
    w('nghìn', 554, 346, 103, 41, 96),
    w('mươi', 947, 346, 95, 32, 81),
    w('sáu', 1057, 346, 59, 32, 96),
    w('trăm', 326, 348, 82, 30, 96),
    w('năm', 670, 348, 78, 30, 93),
    w('trắm', 760, 348, 84, 30, 89),      # `trăm` — same
    w('năm', 856, 348, 78, 30, 96),
    w('năm', 465, 349, 75, 29, 96),
    w('lập', 711, 660, 57, 42, 96),
    w('kê', 893, 660, 43, 33, 96),
    w('Người', 578, 661, 118, 41, 58),
    w('bảng', 783, 661, 96, 41, 96),
    w('“..Z', 650, 767, 280, 128, 0),     # the signature
    w('Tám', 831, 925, 149, 43, 93),
    w('Trần', 534, 926, 89, 32, 96),
    w('Văn', 637, 926, 66, 42, 96),
    w('Bảy', 718, 926, 100, 33, 95),
]


class TestFindingTheTotal:
    def test_reads_the_real_page(self):
        read = pl.read_total({7: REAL_PAGE_8})

        assert read.amount == 240_305_556
        assert read.page == 7

    def test_the_digits_and_the_words_are_read_separately(self):
        read = pl.read_total({7: REAL_PAGE_8})

        assert read.digits == 240_305_556
        assert read.words == 240_305_556
        assert read.reason == "digits-and-words-agree"

    def test_it_marks_where_the_number_is(self):
        read = pl.read_total({7: REAL_PAGE_8})

        assert read.bbox is not None
        assert read.bbox["width"] > 0
        assert read.confidence > 80

    def test_it_searches_every_page_and_names_the_one_it_found(self):
        read = pl.read_total({2: line("một dòng nào đó", 500), 7: REAL_PAGE_8})
        assert read.page == 7

    def test_a_listing_with_no_total_is_not_found(self):
        read = pl.read_total({2: line("Tên người bán Địa chỉ Số căn cước", 100)})

        assert read.amount is None
        assert read.reason == "not-found"
        assert read.page is None

    def test_no_pages_at_all(self):
        read = pl.read_total({})
        assert read.amount is None
        assert read.reason == "not-found"


class TestTheTwoReadsMustAgree:
    def test_a_digit_slip_is_caught_and_refused(self):
        """The reason this parser reads the amount twice: one OCR slip in the
        digits would turn #20 into a false accusation against the roster."""
        page = line("Tổng giá trị hàng hóa, dịch vụ mua vào: 240.305.558VNĐ "
                    "(Số tiền bằng chữ : Hai trăm bốn mươi triệu", 290) \
            + line("ba trăm lẻ năm nghìn năm trăm năm mươi sáu đồng).", 346)

        read = pl.read_total({7: page})

        assert read.amount is None
        assert read.reason == "digits-and-words-disagree"
        assert read.digits == 240_305_558
        assert read.words == 240_305_556

    def test_digits_alone_are_accepted_but_recorded_as_such(self):
        page = line("Tổng giá trị hàng hóa, dịch vụ mua vào: 240.305.556VNĐ", 290)

        read = pl.read_total({7: page})

        assert read.amount == 240_305_556
        assert read.reason == "digits-only"
        assert read.words is None

    def test_words_alone_are_accepted_too(self):
        page = line("Tổng giá trị hàng hóa, dịch vụ mua vào: "
                    "(Số tiền bằng chữ : Một triệu đồng).", 290)

        read = pl.read_total({7: page})

        assert read.amount == 1_000_000
        assert read.reason == "words-only"
        assert read.digits is None

    def test_a_label_with_no_number_beside_it_is_not_a_total(self):
        # Indistinguishable from the table's column header, which carries the
        # same words -- so "not-found" is the only honest answer.
        read = pl.read_total({7: line("Tổng giá trị hàng hóa, dịch vụ mua vào:", 290)})

        assert read.amount is None
        assert read.reason == "not-found"


class TestScopingTheWords:
    def test_a_date_after_the_words_is_not_read_as_a_number(self):
        """`năm` is both "five" and "year". Reading past the closing paren
        would turn `năm 2026` into a stray 5."""
        page = line("Tổng giá trị hàng hóa, dịch vụ mua vào: 1.000.000VNĐ "
                    "(Số tiền bằng chữ : Một triệu đồng). Ngày 26 tháng 07 "
                    "năm 2026", 290)

        read = pl.read_total({7: page})

        assert read.words == 1_000_000
        assert read.amount == 1_000_000

    def test_words_are_read_only_after_the_bang_chu_marker(self):
        # "Tổng" and "giá trị" contain no number words, but a preparer's name
        # further down the page might.
        page = (line("Tổng giá trị hàng hóa, dịch vụ mua vào: 1.000.000VNĐ "
                     "(Số tiền bằng chữ : Một triệu đồng).", 290)
                + line("Người lập bảng kê Trần Năm Bảy", 661))

        read = pl.read_total({7: page})

        assert read.words == 1_000_000


class TestMoneyTokens:
    def test_dot_grouped(self):
        assert pl.money_token("240.305.556") == 240_305_556

    def test_with_currency_suffix(self):
        assert pl.money_token("240.305.556VNĐ") == 240_305_556
        assert pl.money_token("8.888.889đ") == 8_888_889
        assert pl.money_token("1.000.000 VND") == 1_000_000

    def test_comma_grouped(self):
        assert pl.money_token("240,305,556") == 240_305_556

    def test_a_missing_group_separator_is_still_read(self):
        # Tesseract returned `8333.333` for `8.333.333` on a real row.
        assert pl.money_token("8333.333") == 8_333_333

    def test_not_money(self):
        for text in ("", "abc", "01/07/2026", "0303490096", "-", "1"):
            assert pl.money_token(text) is None, text

    def test_a_five_digit_leading_group_is_refused(self):
        # Beyond four the token is not a dropped separator any more.
        assert pl.money_token("83333.333") is None

    def test_a_bare_thousand_is_not_a_grouped_number(self):
        # No separator at all: could be a quantity, an ID, anything.
        assert pl.money_token("8888889") is None


class TestTheColumnHeaderIsNotTheTotal:
    """The table's own column header reads `Hàng hóa, dịch vụ mua vào` — the
    same phrase as the total label. Anchoring alone matched the header on page 3
    of the real submission and never reached the total on page 8."""

    REAL_HEADER = line("Ngày Người bán Hàng hóa, dịch vụ mua vào Ghi", 1020)

    def test_a_header_alone_finds_no_total(self):
        read = pl.read_total({2: self.REAL_HEADER})

        assert read.amount is None
        assert read.reason == "not-found"

    def test_the_header_does_not_mask_the_total_pages_later(self):
        read = pl.read_total({2: self.REAL_HEADER, 7: REAL_PAGE_8})

        assert read.amount == 240_305_556
        assert read.page == 7

    def test_a_corroborated_read_beats_a_digits_only_one(self):
        stray = line("Tổng giá trị hàng hóa, dịch vụ mua vào: 999.999.999", 400)
        read = pl.read_total({2: stray, 7: REAL_PAGE_8})

        assert read.amount == 240_305_556
        assert read.reason == "digits-and-words-agree"

    def test_a_disagreement_is_still_reported_when_it_is_all_there_is(self):
        page = line("Tổng giá trị hàng hóa, dịch vụ mua vào: 240.305.558VNĐ "
                    "(Số tiền bằng chữ : Một triệu đồng).", 290)
        read = pl.read_total({2: self.REAL_HEADER, 7: page})

        assert read.reason == "digits-and-words-disagree"
        assert read.amount is None


#: Page 7 of the February submission, verbatim. Tesseract read the `8` in
#: `258.638.890` as `§`, so the digit read fails outright — the spelled-out
#: amount is the only working read on this page. This is not a hypothetical:
#: it is one of the two real submissions.
REAL_FEB_PAGE_7 = [
    w('-', 330, 500, 12, 4, 92),
    w('Tông', 354, 500, 95, 50, 96),
    w('giá', 462, 500, 51, 41, 96),
    w('trị', 528, 500, 36, 39, 96),
    w('hàng', 581, 500, 87, 41, 96),
    w('hóa', 681, 500, 65, 38, 96),
    w('mua', 760, 500, 78, 22, 96),
    w('vào:', 849, 500, 74, 32, 93),
    w('25§.638.890VND', 939, 500, 323, 32, 84),
    w('(Băng', 1275, 500, 90, 51, 96),
    w('chữ:', 1397, 500, 67, 34, 96),
    w('Hai', 1490, 500, 64, 32, 96),
    w('trăm', 1566, 500, 82, 30, 96),
    w('năm', 1661, 500, 75, 29, 96),
    w('mươi', 1752, 500, 96, 33, 96),
    w('tám', 1860, 500, 59, 32, 96),
    w('triệu', 1938, 500, 83, 39, 96),
    w('sáu', 2034, 500, 59, 32, 95),
    w('trăm', 2108, 500, 82, 30, 96),
    w('ba', 2201, 500, 39, 32, 96),
] + line("mươi tám nghìn tám trăm chín mươi đồng).", 560)


class TestDamagedDigits:
    def test_february_resolves_on_the_words_alone(self):
        read = pl.read_total({6: REAL_FEB_PAGE_7})

        assert read.words == 258_638_890
        assert read.amount == 258_638_890

    def test_the_damaged_digits_are_repaired_and_then_corroborate(self):
        """`§` is a known Tesseract stand-in for `8`. A repair is only
        accepted when it reproduces the spelled-out amount exactly, so the
        words stay the authority and the repair can never invent a value."""
        read = pl.read_total({6: REAL_FEB_PAGE_7})

        assert read.digits == 258_638_890
        assert read.digits_repaired is True
        assert read.reason == "digits-and-words-agree"

    def test_a_clean_read_is_not_marked_repaired(self):
        read = pl.read_total({7: REAL_PAGE_8})
        assert read.digits_repaired is False

    def test_a_repair_that_does_not_match_the_words_is_refused(self):
        page = (line("Tổng giá trị hàng hóa mua vào: 25§.638.890VND", 500)
                + line("(Bằng chữ: Chín trăm nghìn đồng).", 560))

        read = pl.read_total({6: page})

        # No substitution of `§` produces 900,000, and a money-shaped token is
        # plainly printed — so this is a contradiction on the page, not a page
        # that simply omits the digits.
        assert read.words == 900_000
        assert read.amount is None
        assert read.reason == "digits-and-words-disagree"
        assert read.digits_repaired is False

    def test_a_page_that_prints_no_digits_at_all_is_words_only(self):
        page = line("Tổng giá trị hàng hóa mua vào: (Bằng chữ: Chín trăm "
                    "nghìn đồng).", 500)

        read = pl.read_total({6: page})

        assert read.reason == "words-only"
        assert read.amount == 900_000

    def test_damaged_digits_with_no_words_stay_unreadable(self):
        read = pl.read_total({6: line("Tổng giá trị hàng hóa mua vào: 25§.638.890VND", 500)})

        # nothing to validate a repair against, so no repair is attempted
        assert read.reason == "not-found"


class TestRepairCandidates:
    def test_the_common_substitutions(self):
        assert 258_638_890 in pl.digit_repairs("25§.638.890")
        assert 1_000_000 in pl.digit_repairs("l.000.000")
        assert 500_000 in pl.digit_repairs("5OO.0O0")

    def test_a_clean_token_needs_no_repair(self):
        assert pl.digit_repairs("240.305.556") == {240_305_556}

    def test_it_refuses_to_explode_combinatorially(self):
        # Six damaged characters is not OCR noise, it is an unreadable token.
        assert pl.digit_repairs("§§§.§§§.§§§") == set()

    def test_a_token_with_no_digits_at_all(self):
        assert pl.digit_repairs("Người") == set()
