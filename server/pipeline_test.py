import os

import pipeline as pl
# `pipeline` puts the splitter on sys.path, so this import must follow it.
import detect_packets as dp_real  # noqa: E402

#: Captured at import, before any monkeypatching: `pl.dp` and `dp_real` are the
#: same module object, so reading the attribute later would return the fake that
#: `_install_fake_detection` put there.
_REAL_PACKETS_FROM_COVERS = dp_real.packets_from_covers
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


def test_all_roster_rows_reads_the_combined_template_header():
    """The combined workbook labels its columns differently, and matching broke
    silently on it: `_ROSTER_HEADER_MAP` was an exact-string table wanting
    "số cccd", so "CCCD/ PP" never matched, `all_roster_rows` returned [], every
    matching index was empty and all 25 packets came out `unmatched` -- while the
    roster count still said 25, because roster_checks parses the same sheet with
    regexes and got it right. One template, two parsers, one of them updated."""
    rows = [
        ["THANH TOÁN DỊCH VỤ"],
        ["Mã eform plan:", None],
        [None, None],
        ["STT", "Họ và tên", "CCCD/ PP", "MST", "Ngày/ tháng/ năm sinh",
         "Giới tính", "Số tài khoản", "Ngân hàng"],
        [None, None, None, None, None, None, None, None],
        ["1", "NGUYEN VAN MOT", "001100000001", "001100000001", "07/05/2001",
         "NAM", "1900000001", "Techcombank"],
        ["2", "TRAN THI HAI", "001100000002", "001100000002", "19/08/2005",
         "NỮ", "1900000002", "Vietcombank"],
    ]

    out = all_roster_rows(rows)

    assert [r["name"] for r in out] == ["NGUYEN VAN MOT", "TRAN THI HAI"]
    assert [r["cccd"] for r in out] == ["001100000001", "001100000002"]
    assert out[0]["mst"] == "001100000001"
    assert out[0]["ngaysinh"] == "07/05/2001"
    assert out[0]["tk"] == "1900000001"


def test_all_roster_rows_finds_a_pay_column_labelled_a_row_lower():
    """The combined template stacks "Chi Phí (+ PIT)" over "Gross", so the pay
    column is named one row below the row that names the person. Reading only the
    name row left `phi` empty, which silently disables the Gross comparison."""
    rows = [
        ["STT", "Họ và tên", "CCCD/ PP", "Chi Phí (+ PIT)", None],
        [None, None, None, "Gross", "Thuế PIT"],
        ["1", "NGUYEN VAN MOT", "001100000001", "4400000", "0"],
    ]

    out = all_roster_rows(rows)

    assert len(out) == 1
    assert out[0]["phi"] == "4400000"


def test_build_roster_index_indexes_the_combined_template():
    """The end of the same failure: an empty index means every packet is
    unmatched no matter how cleanly its identity was read."""
    rows = [
        ["STT", "Họ và tên", "CCCD/ PP", "MST", "Số tài khoản"],
        ["1", "NGUYEN VAN MOT", "001100000001", "001100000001", "1900000001"],
    ]

    by_cccd, by_name, by_mst = build_roster_index(rows)

    assert "001100000001" in by_cccd
    assert by_cccd["001100000001"]["name"] == "NGUYEN VAN MOT"
    row, how = match_roster("001100000001", "NGUYÊN VAN MOT", by_cccd, by_name,
                            by_mst=by_mst)
    assert how == "cccd"


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
    by_cccd, by_name, _by_mst = build_roster_index(rows)
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


#: `page_reader` mirrors the real ocr_packet signature: the pipeline threads the
#: IDP escalation reader through, and it is None unless IDP is configured.
def _fake_ocr_packet(pdf_path, start, end, out_dir, page_reader=None, **kwargs):
    _fake_ocr_packet.page_readers.append(page_reader)
    os.makedirs(out_dir, exist_ok=True)
    identity = (
        {"cccd": "048091001309", "name": "Nguyễn Văn A"} if start == 0
        else {"cccd": "000000000000", "name": "Không Ai Cả"}
    )
    fields = [{"key": "hoten", "expected": "", "sources": []}]
    return {"folder": {"docs": [], "fields": fields}, "identity": identity}


_fake_ocr_packet.page_readers = []


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


# ---------------------------------------------------------------------------
# Boundary snapping: covers land mid-packet, so they are moved back to the page
# that starts one.
# ---------------------------------------------------------------------------

class TestStartPageClassifier:
    def test_it_classifies_a_page_by_its_title(self, monkeypatch):
        monkeypatch.setattr(pl.oc, "ocr_words",
                            lambda *a, **k: ([{"text": "HỢP", "x": 0, "y": 0,
                                               "w": 9, "h": 9, "conf": 90.0},
                                              {"text": "DỊCH", "x": 20, "y": 0,
                                               "w": 9, "h": 9, "conf": 90.0},
                                              {"text": "VỤ", "x": 40, "y": 0,
                                               "w": 9, "h": 9, "conf": 90.0}], 1.0))

        classify = pl._start_page_classifier("x.pdf")

        assert classify(0) == "contract"

    def test_an_unreadable_page_is_not_a_kind(self, monkeypatch):
        monkeypatch.setattr(pl.oc, "ocr_words", lambda *a, **k: ([], 1.0))
        assert pl._start_page_classifier("x.pdf")(0) is None

    def test_an_ocr_failure_does_not_stop_the_ingest(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("tesseract fell over")
        monkeypatch.setattr(pl.oc, "ocr_words", boom)

        # A page that cannot be read is simply not a start; splitting continues.
        assert pl._start_page_classifier("x.pdf")(0) is None

    def test_it_reads_each_page_once(self, monkeypatch):
        reads = []

        def ocr(pdf_path, page, **kwargs):
            reads.append(page)
            return [], 1.0
        monkeypatch.setattr(pl.oc, "ocr_words", ocr)

        classify = pl._start_page_classifier("x.pdf")
        classify(3), classify(3), classify(3)

        assert reads == [3]


class TestRunPipelineSnapsBoundaries:
    def _install(self, monkeypatch, covers, kinds, pages=12):
        """Fake detection over a `pages`-page document, but with the real
        `packets_from_covers` so the bounds under test are actually derived."""
        _install_fake_detection(monkeypatch)
        monkeypatch.setattr(
            pl.dp, "load_page_bands",
            lambda pdf_path: ([None] * pages, [1.0] * pages,
                              [0.001] * pages, pages))
        monkeypatch.setattr(pl.dp, "packets_from_covers",
                            _REAL_PACKETS_FROM_COVERS)
        monkeypatch.setattr(pl.dp, "covers_from_scores",
                            lambda scores, threshold: covers)
        monkeypatch.setattr(pl.dp, "prune_excess_covers",
                            lambda cover_pages, scores, roster_n: (cover_pages, []))
        monkeypatch.setattr(pl, "_start_page_classifier",
                            lambda pdf_path, **k: lambda page: kinds.get(page))

    def test_the_packets_start_where_the_documents_do(self, tmp_path, monkeypatch):
        # covers three pages late, as on the real submission
        self._install(monkeypatch, [3, 9], {0: "contract", 6: "contract"})

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert [p["pages"] for p in result["packets"]] == [[0, 5], [6, 11]]

    def test_it_reports_what_it_moved(self, tmp_path, monkeypatch):
        self._install(monkeypatch, [3, 9], {0: "contract", 6: "contract"})

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert result["summary"]["boundaries_snapped"] == 2

    def test_a_submission_with_no_contract_pages_is_left_alone(
        self, tmp_path, monkeypatch,
    ):
        """The PUBGm nghiệm thu submission has no contracts. Its boundaries must
        not move on a guess."""
        self._install(monkeypatch, [0, 3], {})

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert [p["pages"] for p in result["packets"]] == [[0, 2], [3, 11]]
        assert result["summary"]["boundaries_snapped"] == 0


class TestRunPipelineSplitsMergedPackets:
    """Five July packets ran 14-16 pages against a median of 8, each holding two
    CTVs, because a cover was never found. Their interiors carry the contract
    page the boundary belongs on."""

    def _install(self, monkeypatch, covers, kinds, pages=32):
        _install_fake_detection(monkeypatch)
        monkeypatch.setattr(
            pl.dp, "load_page_bands",
            lambda pdf_path: ([None] * pages, [1.0] * pages,
                              [0.001] * pages, pages))
        monkeypatch.setattr(pl.dp, "packets_from_covers",
                            _REAL_PACKETS_FROM_COVERS)
        monkeypatch.setattr(pl.dp, "covers_from_scores",
                            lambda scores, threshold: covers)
        monkeypatch.setattr(pl.dp, "prune_excess_covers",
                            lambda cover_pages, scores, roster_n: (cover_pages, []))
        monkeypatch.setattr(pl, "_start_page_classifier",
                            lambda pdf_path, **k: lambda page: kinds.get(page))

    def test_a_merged_packet_becomes_two(self, tmp_path, monkeypatch):
        # covers at 0, 8, 24 — the one at 16 was never found
        kinds = {p: "contract" for p in (0, 8, 16, 24)}
        self._install(monkeypatch, [0, 8, 24], kinds)

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert [p["pages"] for p in result["packets"]] == [
            [0, 7], [8, 15], [16, 23], [24, 31],
        ]
        assert result["summary"]["boundaries_inserted"] == 1

    def test_the_inserted_packet_is_flagged_as_inferred(
        self, tmp_path, monkeypatch,
    ):
        kinds = {p: "contract" for p in (0, 8, 16, 24)}
        self._install(monkeypatch, [0, 8, 24], kinds)

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        flags = {p["index"]: p["flags"] for p in result["packets"]}
        assert "inferred-boundary" in flags[2]
        assert "inferred-boundary" not in flags[0]

    def test_a_submission_with_even_packets_is_untouched(
        self, tmp_path, monkeypatch,
    ):
        kinds = {p: "contract" for p in (0, 8, 16, 24)}
        self._install(monkeypatch, [0, 8, 16, 24], kinds)

        result = pl.run_pipeline(
            str(tmp_path / "in.pdf"), None, str(tmp_path), lambda *a: None,
        )

        assert len(result["packets"]) == 4
        assert result["summary"]["boundaries_inserted"] == 0


# ---------------------------------------------------------------------------
# Matching on the personal MST.
#
# The July packet that matched no roster row is row 32's. Its number is printed
# on three of its pages, and `extract_fields` reads it cleanly at 0.95 — but
# under the `mst` key, because the CCCD label was split by line grouping while
# the `MSTTNCN` label survived. `match_roster` only ever tried the CCCD and then
# the name, so a strong identifier already in hand went unused and the packet
# fell through to `unmatched`.
# ---------------------------------------------------------------------------

_MST_ROWS = [
    ["Họ và tên", "Số CCCD", "MST", "Ngày tháng năm sinh", "Số TK",
     "Phí dịch vụ", "Note"],
    ["Phan Tấn Tài", "060203014847", "060203014847", "01/01/2003",
     "19001234567", "1.000.000", "Demo"],
    ["Nguyễn Văn B", "079303009457", "8765432109", "02/02/1990",
     "19009876543", "2.000.000", "Demo"],
]


class TestMatchingOnTheMst:
    def _index(self):
        return pl.build_roster_index(_MST_ROWS)

    def test_the_mst_matches_when_the_cccd_was_not_read(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster("", "", by_cccd, by_name, mst="060203014847",
                              by_mst=by_mst)

        assert how == "mst"
        assert row["name"] == "Phan Tấn Tài"

    def test_an_mst_that_differs_from_the_cccd_still_matches(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster("", "", by_cccd, by_name, mst="8765432109",
                              by_mst=by_mst)

        assert how == "mst"
        assert row["name"] == "Nguyễn Văn B"

    def test_the_cccd_still_wins_when_both_are_read(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster(
            "079303009457", "", by_cccd, by_name, mst="060203014847",
            by_mst=by_mst,
        )

        assert how == "cccd"
        assert row["name"] == "Nguyễn Văn B"

    def test_the_mst_beats_the_name(self):
        """A name is the weakest key and the wrong-person error is the most
        expensive one this tool can make, so a strong identifier goes first."""
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster(
            "", "Nguyễn Văn B", by_cccd, by_name, mst="060203014847",
            by_mst=by_mst,
        )

        assert how == "mst"
        assert row["name"] == "Phan Tấn Tài"

    def test_the_name_still_works_with_no_numbers_at_all(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster("", "Phan Tấn Tài", by_cccd, by_name)

        assert how == "name"

    def test_an_unknown_mst_does_not_match(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster("", "", by_cccd, by_name, mst="111111111111",
                              by_mst=by_mst)

        assert row is None
        assert how == "unmatched"

    def test_the_mst_index_is_keyed_on_digits(self):
        by_cccd, by_name, by_mst = self._index()

        assert "060203014847" in by_mst
        assert "8765432109" in by_mst

    def test_a_roster_row_whose_mst_repeats_keeps_the_first(self):
        rows = _MST_ROWS + [["Trùng MST", "099999999999", "060203014847",
                            "03/03/1993", "1", "1", ""]]
        by_cccd, by_name, by_mst = pl.build_roster_index(rows)

        assert by_mst["060203014847"]["name"] == "Phan Tấn Tài"

    def test_the_call_still_works_without_the_mst_argument(self):
        by_cccd, by_name, by_mst = self._index()

        row, how = pl.match_roster("060203014847", "", by_cccd, by_name)

        assert how == "cccd"


def test_the_ingest_is_local_only_unless_idp_is_configured(monkeypatch, tmp_path):
    """No packet page leaves the workstation by default.

    The escalation reader is threaded through to ocr_packet, and it is None
    unless GREENNODE_IDP_URL and GREENNODE_API_KEY are both set -- so enabling
    IDP is a deliberate deployment choice, not a default.
    """
    for var in ("GREENNODE_IDP_URL", "GREENNODE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert pl._page_reader() is None

    monkeypatch.setenv("GREENNODE_IDP_URL", "http://idp.example/v1")
    monkeypatch.setenv("GREENNODE_API_KEY", "not-a-real-key")
    # The two variables alone enable the CCCD card reader -- that path is proven
    # (42 cards read, 39 attached). Document-field escalation needs an explicit
    # IDP_DOC_TYPE on top, because no value for a general page read is known to
    # work yet and every candidate returns HTTP 500.
    assert callable(pl._card_reader())
    monkeypatch.delenv("IDP_DOC_TYPE", raising=False)
    assert pl._page_reader() is None
    monkeypatch.setenv("IDP_DOC_TYPE", "GENERAL")
    assert callable(pl._page_reader())
