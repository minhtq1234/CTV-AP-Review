import os

import pipeline as pl
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


# ---------------------------------------------------------------------------
# run_pipeline: packet meta carries matchedBy + ocr/roster identities (Task 3)
#
# Fakes out detect_packets' PDF-derived detection (load_page_bands et al. --
# these need a real PDF/np arrays) with a fixed 2-packet/6-page split, and
# ocr_extract.ocr_packet (needs real OCR) with a stub identity per packet --
# but keeps every pure text/list function (reconcile, coarse_label,
# extract_roster_names, oc.norm/_slug/build_manifest/FIELD_SPECS) real, so
# this exercises the actual roster-matching + manifest-writing code path.
# ---------------------------------------------------------------------------

_ROSTER_ROWS = [
    ["Họ và tên", "Số CCCD", "MST", "Ngày tháng năm sinh", "Số TK", "Phí dịch vụ", "Note"],
    ["Nguyễn Văn A", "048091001309", "048091001309", "24/04/1991", "19001234567",
     "10.000.000", "Danh Tướng 3Q - 381"],
]

_FAKE_BOUNDS = [(0, 2), (3, 5)]  # 2 packets, 3 pages each, 6 pages total


def _fake_ocr_packet(pdf_path, start, end, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    identity = (
        {"cccd": "048091001309", "name": "Nguyễn Văn A"} if start == 0
        else {"cccd": "000000000000", "name": "Không Ai Cả"}
    )
    fields = [{"key": "hoten", "expected": "", "sources": []}]
    return {"folder": {"docs": [], "fields": fields}, "identity": identity}


def _install_fake_detection(monkeypatch):
    """Stub the PDF/image-dependent detect_packets calls `run_pipeline` makes,
    leaving the pure list-based ones (reconcile, coarse_label, ...) real."""
    n = 6
    monkeypatch.setattr(pl.dp, "load_page_bands",
                         lambda pdf_path: ([None] * n, [1.0] * n, [0.001] * n, n))
    monkeypatch.setattr(pl.dp, "seed_scores", lambda bands: ([0.0] * len(bands), 0))
    monkeypatch.setattr(pl.dp, "derive_threshold", lambda scores: 0.5)
    monkeypatch.setattr(pl.dp, "covers_from_scores", lambda scores, threshold: [0, 3])
    monkeypatch.setattr(pl.dp, "prune_excess_covers",
                         lambda cover_pages, scores, roster_n: (cover_pages, []))
    monkeypatch.setattr(pl.dp, "packets_from_covers", lambda cover_pages, n: _FAKE_BOUNDS)
    monkeypatch.setattr(pl.oc, "ocr_packet", _fake_ocr_packet)


def test_packet_meta_carries_match_key_and_identities(tmp_path, monkeypatch):
    _install_fake_detection(monkeypatch)
    monkeypatch.setattr(pl, "load_roster_rows", lambda path: _ROSTER_ROWS)

    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"), "roster.xlsx", str(tmp_path), lambda *a: None,
    )

    packets = result["packets"]
    assert len(packets) == 2

    # packet 0's OCR'd identity hits the roster row by CCCD.
    p0 = packets[0]
    assert p0["matchedBy"] == "cccd"
    assert set(p0["ocrIdentity"]) == {"cccd", "name"}
    assert p0["ocrIdentity"] == {"cccd": "048091001309", "name": "Nguyễn Văn A"}
    assert p0["rosterIdentity"] == {"cccd": "048091001309", "name": "Nguyễn Văn A"}

    # packet 1's OCR'd identity matches no one in the (1-row) roster.
    p1 = packets[1]
    assert p1["matchedBy"] == "unmatched"
    assert set(p1["ocrIdentity"]) == {"cccd", "name"}
    assert p1["ocrIdentity"] == {"cccd": "000000000000", "name": "Không Ai Cả"}
    assert p1["rosterIdentity"] is None

    for p in packets:
        assert p["matchedBy"] in ("cccd", "name", "unmatched", "no-roster")
        assert p["rosterIdentity"] is None or set(p["rosterIdentity"]) == {"cccd", "name"}


def test_packet_meta_no_roster_is_no_roster_with_null_identity(tmp_path, monkeypatch):
    _install_fake_detection(monkeypatch)

    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"), None, str(tmp_path), lambda *a: None,
    )

    packets = result["packets"]
    assert len(packets) == 2
    for p in packets:
        assert p["matchedBy"] == "no-roster"
        assert p["rosterIdentity"] is None
        assert set(p["ocrIdentity"]) == {"cccd", "name"}


def test_cccd_ingest_runs_after_packet_manifests_and_returns_workbook(
    tmp_path,
    monkeypatch,
):
    _install_fake_detection(monkeypatch)
    monkeypatch.setattr(pl, "load_roster_rows", lambda path: _ROSTER_ROWS)
    seen = {}
    workbook = {
        "status": "ready",
        "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
        "mappings": [],
    }

    def fake_ingest(
        xlsx_path,
        roster_rows,
        packets,
        case_dir,
        manifest_paths,
        assets_dir,
        progress_cb,
        analyze=None,
    ):
        seen["xlsx_path"] = xlsx_path
        seen["roster_rows"] = roster_rows
        seen["manifest_paths"] = manifest_paths
        seen["manifests_exist"] = all(
            os.path.isfile(path) for path in manifest_paths.values()
        )
        return {"packets": packets, "cccdWorkbook": workbook}

    monkeypatch.setattr(pl, "ingest_cccd_workbook", fake_ingest)

    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        "roster.xlsx",
        str(tmp_path),
        lambda *args: None,
        cccd_xlsx_path="cards.xlsx",
    )

    assert result["cccdWorkbook"] == workbook
    assert seen["xlsx_path"] == "cards.xlsx"
    assert seen["roster_rows"][0]["cccd"] == "048091001309"
    assert seen["manifests_exist"] is True
    assert set(seen["manifest_paths"]) == {0, 1}


def test_legacy_pipeline_call_returns_null_cccd_workbook(tmp_path, monkeypatch):
    _install_fake_detection(monkeypatch)

    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        None,
        str(tmp_path),
        lambda *args: None,
    )

    assert result["cccdWorkbook"] is None


if __name__ == "__main__":
    import inspect
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            if inspect.signature(f).parameters:
                continue  # needs pytest fixtures (monkeypatch/tmp_path) -- see pytest run below
            f(); print(f"  ok {n}")
    print("ALL OK (run fixture-based tests via: python3 -m pytest pipeline_test.py)")


def _packet(index, cccd="", name=""):
    return {
        "index": index,
        "flags": [],
        "rosterIdentity": {"cccd": cccd, "name": name} if (cccd or name) else None,
    }


def test_two_packets_claiming_one_roster_row_are_both_flagged():
    # The bảng kê holds one row per person -- one payment. Both packets must be
    # told about each other; neither may look clean on its own.
    packets = [_packet(0, "079303009457"), _packet(1, "079303009457")]

    pl.flag_duplicate_identities(packets)

    assert all(pl.DUPLICATE_IDENTITY_FLAG in p["flags"] for p in packets)
    assert packets[0]["duplicateOf"] == [1]
    assert packets[1]["duplicateOf"] == [0]


def test_a_unique_identity_is_not_flagged():
    packets = [_packet(0, "079303009457"), _packet(1, "001204004530")]

    pl.flag_duplicate_identities(packets)

    assert all(p["flags"] == [] for p in packets)
    assert all("duplicateOf" not in p for p in packets)


def test_packets_with_no_roster_row_are_left_alone():
    packets = [_packet(0), _packet(1)]

    pl.flag_duplicate_identities(packets)

    assert all(p["flags"] == [] for p in packets)


def test_a_name_only_match_still_collides():
    # A packet matched by name has no CCCD on its roster identity; the name is
    # then the only key available, and two of them still contend for one row.
    packets = [_packet(0, name="Trần Thanh Vân Anh"),
               _packet(1, name="TRAN THANH VAN ANH")]

    pl.flag_duplicate_identities(packets)

    assert all(pl.DUPLICATE_IDENTITY_FLAG in p["flags"] for p in packets)


def test_three_packets_all_reference_each_other():
    packets = [_packet(i, "079303009457") for i in range(3)]

    pl.flag_duplicate_identities(packets)

    assert packets[1]["duplicateOf"] == [0, 2]


# ---------------------------------------------------------------------------
# Bảng Kê Thu Mua total — the batch-level front matter, scanned for criterion
# #20's other half.
# ---------------------------------------------------------------------------

def _words(text, y):
    out, x = [], 300
    for token in text.split():
        out.append({"text": token, "x": x, "y": y, "w": len(token) * 20,
                    "h": 30, "conf": 95.0})
        x += len(token) * 20 + 20
    return out


_TOTAL_LINE = _words(
    "Tổng giá trị hàng hóa, dịch vụ mua vào: 240.305.556VNĐ "
    "(Số tiền bằng chữ : Hai trăm bốn mươi triệu ba trăm lẻ năm nghìn "
    "năm trăm năm mươi sáu đồng).", 500,
)


def _pages(**by_index):
    """A fake OCR reader over `{page_index: words}`."""
    pages = {int(k.lstrip("p")): v for k, v in by_index.items()}

    def read(pdf_path, page, **kwargs):
        return pages.get(page, []), 1.0
    return read


def _upright(*args, **kwargs):
    """Rotation detection needs a real PDF; these tests scan word lists."""
    return 0


def _scan(front_pages, ocr):
    return pl.read_purchase_total(
        "x.pdf", front_pages=front_pages, ocr=ocr, detect_rotation=_upright,
    )


class TestPurchaseTotal:
    def test_finds_the_total_in_the_front_matter(self):
        read = _scan(8, _pages(p7=_TOTAL_LINE))

        assert read["gross"] == 240_305_556
        assert read["page"] == 7
        assert read["reason"] == "digits-and-words-agree"

    def test_it_scans_backwards_so_the_last_page_is_reached_first(self):
        """The total is the last thing on the listing, so counting down finds
        it without OCRing the rows above it."""
        seen = []

        def ocr(pdf_path, page, **kwargs):
            seen.append(page)
            return (_TOTAL_LINE if page == 7 else []), 1.0

        _scan(11, ocr)

        assert seen == [10, 9, 8, 7]

    def test_no_front_matter_means_no_listing(self):
        calls = []

        def ocr(pdf_path, page, **kwargs):
            calls.append(page)
            return [], 1.0

        assert _scan(0, ocr) is None
        assert calls == []

    def test_a_submission_with_no_listing_returns_none(self):
        # The PUBGm nghiệm thu submission: 32 front pages, no purchase listing.
        read = _scan(32, _pages())
        assert read is None

    def test_it_reports_a_repaired_digit_read(self):
        page = _words("Tổng giá trị hàng hóa mua vào: 25§.638.890VND "
                      "(Bằng chữ: Hai trăm năm mươi tám triệu sáu trăm ba "
                      "mươi tám nghìn tám trăm chín mươi đồng).", 500)

        read = _scan(7, _pages(p6=page))

        assert read["gross"] == 258_638_890
        assert read["digitsRepaired"] is True

    def test_a_contradictory_page_yields_no_amount_and_says_why(self):
        page = _words("Tổng giá trị hàng hóa mua vào: 240.305.558VNĐ "
                      "(Số tiền bằng chữ : Một triệu đồng).", 500)

        read = _scan(7, _pages(p6=page))

        assert read is not None
        assert read["gross"] is None
        assert read["reason"] == "digits-and-words-disagree"
        assert read["page"] == 6

    def test_the_scan_is_capped_and_says_when_the_cap_bit(self):
        scanned = []

        def ocr(pdf_path, page, **kwargs):
            scanned.append(page)
            return [], 1.0

        read = _scan(pl.MAX_FRONT_MATTER_PAGES + 5, ocr)

        assert len(scanned) == pl.MAX_FRONT_MATTER_PAGES
        assert read == {"gross": None, "page": None,
                        "reason": "front-matter-too-long",
                        "digitsRepaired": False,
                        "pagesScanned": pl.MAX_FRONT_MATTER_PAGES}


class TestRunPipelineCarriesTheTotal:
    def test_the_total_reaches_the_result(self, tmp_path, monkeypatch):
        _install_fake_detection(monkeypatch)
        monkeypatch.setattr(pl.dp, "packets_from_covers",
                            lambda cover_pages, n: [(2, 3), (4, 5)])
        monkeypatch.setattr(pl.oc, "ocr_words", _pages(p1=_TOTAL_LINE))
        monkeypatch.setattr(pl.oc, "detect_page_rotation", lambda *a, **k: 0)

        result = pl.run_pipeline(
            str(tmp_path / "input.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert result["purchaseTotal"]["gross"] == 240_305_556

    def test_a_packet_starting_on_page_one_has_no_front_matter(
        self, tmp_path, monkeypatch,
    ):
        _install_fake_detection(monkeypatch)

        result = pl.run_pipeline(
            str(tmp_path / "input.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert result["purchaseTotal"] is None
