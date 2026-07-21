from pipeline import digits, match_roster, fill_expected, all_roster_rows, build_roster_index


def test_digits_strips_spaces_and_punct():
    assert digits("048 091 001 309") == "048091001309"
    assert digits("048-091-001.309") == "048091001309"
    assert digits(None) == ""
    assert digits("") == ""


def test_match_roster_exact_cccd_hit():
    by_cccd = {"048091001309": {"name": "Nguyễn Văn A", "cccd": "048091001309"}}
    by_name = {}
    row, how = match_roster("048091001309", "Bất kỳ tên gì", by_cccd, by_name)
    assert how == "cccd"
    assert row["name"] == "Nguyễn Văn A"


def test_match_roster_cccd_miss_falls_back_to_name():
    # Simulates a roster row with a seeded CCCD typo: the OCR'd CCCD from the
    # packet's own documents doesn't hit by_cccd, but the OCR'd name matches
    # the roster row by name -- so the packet still aligns to the right row
    # (and its cccd field will then correctly show a mismatch against the
    # roster's typo'd value).
    by_cccd = {"048091001399": {"name": "Nguyễn Văn A", "cccd": "048091001399"}}
    by_name = {"nguyen van a": {"name": "Nguyễn Văn A", "cccd": "048091001399"}}
    row, how = match_roster("048091001309", "Nguyễn Văn A", by_cccd, by_name)
    assert how == "name"
    assert row["cccd"] == "048091001399"  # the roster's (typo'd) value, unchanged


def test_match_roster_no_hit_is_unmatched():
    row, how = match_roster("000000000000", "Không Ai Cả", {}, {})
    assert row is None
    assert how == "unmatched"


def test_match_roster_name_match_is_accent_insensitive():
    by_cccd = {}
    by_name = {"nguyen van a": {"name": "Nguyễn Văn A", "cccd": "048091001309"}}
    row, how = match_roster("", "NGUYEN VAN A", by_cccd, by_name)
    assert how == "name"
    assert row["cccd"] == "048091001309"


def test_fill_expected_maps_field_keys_to_roster_row():
    fields = [
        {"key": "hoten", "expected": "", "sources": []},
        {"key": "cccd", "expected": "", "sources": []},
        {"key": "mst", "expected": "", "sources": []},
    ]
    row = {"name": "Nguyễn Văn A", "cccd": "048091001309", "mst": "048091001309"}
    filled = fill_expected(fields, row)
    by_key = {f["key"]: f for f in filled}
    assert by_key["hoten"]["expected"] == "Nguyễn Văn A"
    assert by_key["cccd"]["expected"] == "048091001309"
    assert by_key["mst"]["expected"] == "048091001309"


def test_fill_expected_with_no_row_is_all_empty():
    fields = [{"key": "hoten", "expected": "", "sources": []}]
    filled = fill_expected(fields, None)
    assert filled[0]["expected"] == ""


def test_all_roster_rows_reads_header_and_data():
    rows = [
        ["BẢNG KÊ THANH TOÁN CTV"],
        ["Sản phẩm:", "Foo"],
        ["Họ và tên", "Số CCCD", "MST", "Ngày tháng năm sinh", "Số TK", "Phí dịch vụ", "Note"],
        [None, None, None, None, None, "Gross", None],  # merged sub-header row
        ["Nguyễn Văn A", "048091001309", "048091001309", "24/04/1991", "19001234567", "10.000.000", "Danh Tướng 3Q - 381"],
        ["Trần Thị B", "079123456789", "079123456789", "01/01/1990", "19007654321", "8.000.000", "Liên Quân - 220"],
        [None, None, None, None, None, None, None],
    ]
    out = all_roster_rows(rows)
    assert len(out) == 2
    assert out[0]["name"] == "Nguyễn Văn A"
    assert out[0]["cccd"] == "048091001309"
    assert out[0]["product"] == "Danh Tướng 3Q"
    assert out[1]["name"] == "Trần Thị B"
    assert out[1]["product"] == "Liên Quân"


def test_build_roster_index_keys_by_digits_and_norm_name():
    rows = [
        ["Họ và tên", "Số CCCD", "MST", "Ngày tháng năm sinh", "Số TK", "Phí dịch vụ", "Note"],
        ["Nguyễn Văn A", "048 091 001 309", "048091001309", "24/04/1991", "19001234567", "10.000.000", ""],
    ]
    by_cccd, by_name = build_roster_index(rows)
    assert "048091001309" in by_cccd
    assert by_cccd["048091001309"]["name"] == "Nguyễn Văn A"
    assert "nguyen van a" in by_name


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
