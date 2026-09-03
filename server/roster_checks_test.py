import roster_checks as rc


def sheet(people, *, residence=False, total=None):
    """A roster shaped like Acc's, optionally with the July 'Nơi cư trú' column.

    The two real layouts differ by that one column, which is exactly why the
    checks locate columns by header rather than by position.
    """
    head = ["STT", "Họ và Tên", "Số CCCD", "MST", "Ngày Tháng Năm Sinh",
            "Giới Tính", "Số TK", "Ngân Hàng"]
    if residence:
        head.append("Nơi cư trú")
    head += ["Thời gian làm việc", "Phí dịch vụ", "Chi Phí\n(+ PIT)", "", "", "",
             "Note"]
    second = [""] * len(head)
    gross_at = head.index("Chi Phí\n(+ PIT)")
    second[gross_at:gross_at + 4] = [
        "Gross (1)", "Bản cam kết", "Thuế PIT (2)", "Thực Nhận\n(3 = 1-2)",
    ]
    rows = [
        (None, None, "THANH TOÁN DỊCH VỤ CTV"),
        (None, None, "Sản phẩm: X"),
        tuple(head),
        tuple(second),
    ]

    def line(stt, cccd, mst, dob, account, gross, commitment, pit, net):
        row = [stt, f"Người {stt}", cccd, mst, dob, "Nam", account, "Bank"]
        if residence:
            row.append("Địa chỉ")
        row += ["01/07 - 25/07/2026", gross, gross, commitment, pit, net, ""]
        return tuple(row)

    rows += [line(*p) for p in people]
    if total is not None:
        row = ["Tổng", "", "", "", "", "", "", ""]
        if residence:
            row.append("")
        row += ["", "", total[0], "", total[1], total[2], ""]
        rows.append(tuple(row))
    return rows


GOOD = (1, "079303009457", "079303009457", "03/09/2003", "0081001142415",
        10_000_000, "không", 1_000_000, 9_000_000)


def codes(report):
    return {f.code for f in report.findings}


class TestLayouts:
    def test_finds_columns_in_both_real_layouts(self):
        for residence in (False, True):
            report = rc.check(sheet([GOOD], residence=residence))
            assert report.people == 1
            for name in ("cccd", "gross", "pit", "net", "commitment"):
                assert name in report.columns, (residence, name)

    def test_a_clean_roster_reports_only_the_missing_total(self):
        assert codes(rc.check(sheet([GOOD]))) == {"no-total-row"}


class TestAmounts:
    def test_recomputes_the_formula_rather_than_trusting_it(self):
        bad = (2, "079303009458", "079303009458", "03/09/2003", "111",
               10_000_000, "không", 1_000_000, 8_000_000)  # net is 1m short
        report = rc.check(sheet([GOOD, bad]))
        assert "formula-mismatch" in codes(report)
        finding = next(f for f in report.findings if f.code == "formula-mismatch")
        # the message must state the values and the gap, not just "không khớp"
        assert "10,000,000" in finding.rows[0]
        assert "lệch" in finding.rows[0]

    def test_zero_pit_is_not_answered_here_whatever_the_column_says(self):
        """#15 belongs to the commitment DOCUMENT, not the bảng kê column.

        This module used to answer it off `Bản cam kết`, which records the
        submitter's claim rather than the basis, and the answer reached no
        cell -- `evaluate._pit_basis` was always the one on screen. Two
        sources of truth for one criterion is the thing being prevented, so
        neither column value may produce a roster finding here.
        """
        for stated in ("không", "có"):
            row = (2, "001100000001", "0011000001", "03/09/2003",
                   "1900000001", 2_000_000, stated, 0, 2_000_000)
            report = rc.check(sheet([GOOD, row]))
            assert not [c for c in codes(report) if c.startswith("pit-zero")]

    def test_missing_amounts_are_reported_separately(self):
        blank = (2, "079303009458", "079303009458", "03/09/2003", "111",
                 None, "không", None, None)
        assert "amount-missing" in codes(rc.check(sheet([GOOD, blank])))


class TestSharedValues:
    def test_two_people_sharing_a_cccd(self):
        twin = (2, "079303009457", "079303009458", "03/09/2003", "222",
                1_000_000, "không", 100_000, 900_000)
        report = rc.check(sheet([GOOD, twin]))
        assert "duplicate-cccd" in codes(report)
        assert "dòng 1+2" in next(
            f for f in report.findings if f.code == "duplicate-cccd"
        ).rows

    def test_two_people_sharing_a_bank_account(self):
        twin = (2, "079303009458", "079303009458", "03/09/2003",
                "0081001142415", 1_000_000, "không", 100_000, 900_000)
        assert "duplicate-account" in codes(rc.check(sheet([GOOD, twin])))


class TestFormats:
    def test_a_short_cccd_is_flagged_with_its_length(self):
        short = (2, "0793030094", "079303009458", "03/09/2003", "111",
                 1_000_000, "không", 100_000, 900_000)
        report = rc.check(sheet([GOOD, short]))
        assert "cccd-format" in codes(report)
        assert "10 chữ số" in next(
            f for f in report.findings if f.code == "cccd-format"
        ).rows[0]

    def test_a_malformed_date_of_birth(self):
        odd = (2, "079303009458", "079303009458", "2003-09-03", "111",
               1_000_000, "không", 100_000, 900_000)
        assert "dob-format" in codes(rc.check(sheet([GOOD, odd])))

    def test_a_missing_account(self):
        none = (2, "079303009458", "079303009458", "03/09/2003", "",
                1_000_000, "không", 100_000, 900_000)
        assert "account-missing" in codes(rc.check(sheet([GOOD, none])))


class TestTotals:
    def test_a_matching_total_row_passes(self):
        report = rc.check(sheet([GOOD], total=(10_000_000, 1_000_000, 9_000_000)))
        assert report.ok

    def test_a_mismatched_total_states_the_gap(self):
        report = rc.check(sheet([GOOD], total=(10_000_000, 1_000_000, 8_000_000)))
        assert "total-mismatch-net" in codes(report)
        assert "lệch 1,000,000" in next(
            f for f in report.findings if f.code == "total-mismatch-net"
        ).message
