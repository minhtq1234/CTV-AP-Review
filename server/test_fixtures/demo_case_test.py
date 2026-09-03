import io

from PIL import Image

from test_fixtures import demo_case


def test_page_image_is_a_readable_png_of_the_requested_size():
    data = demo_case.page_png("HỢP ĐỒNG DỊCH VỤ", ["Bên A: VNG", "Bên B: NGUYEN VAN MOT"],
                              width=1000, height=1400)

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.size == (1000, 1400)
    # Not a blank sheet: something was drawn. getcolors rather than getdata,
    # which Pillow deprecated.
    assert len(image.convert("L").getcolors()) > 1


def test_page_image_is_deterministic():
    """The same inputs must give the same bytes, or every rebuild of the demo
    case shows as a change and the fixture stops being a fixture."""
    first = demo_case.page_png("A", ["b"], width=200, height=300)
    second = demo_case.page_png("A", ["b"], width=200, height=300)
    assert first == second


def test_the_demo_people_are_the_repository_s_one_fabricated_series():
    """Two sets of invented identities in one repo means a number in a fixture
    no longer means one person. The demo's identities come from the workbook
    fixture; only the payment detail is added here."""
    from test_fixtures.combined_workbook import PEOPLE as identities

    assert [person["name"] for person in demo_case.PEOPLE] == [
        name for name, _, _ in identities
    ]
    assert [person["cccd"] for person in demo_case.PEOPLE] == [
        cccd for _, cccd, _ in identities
    ]
    assert [person["mst"] for person in demo_case.PEOPLE] == [
        mst for _, _, mst in identities
    ]


def test_every_fabricated_number_is_recognisably_synthetic():
    """The guard that keeps a real contractor out of a committed fixture: every
    identifier belongs to a reserved synthetic range."""
    for person in demo_case.PEOPLE:
        for key in ("cccd", "mst", "tk"):
            value = person[key]
            assert value.isdigit(), f"{key} is not digits: {value}"
            assert value.startswith(("0011", "1900")), (
                f"{key}={value} is outside the synthetic ranges"
            )


def test_built_case_is_shaped_the_way_the_app_reads_it(tmp_path):
    case_dir = demo_case.build(str(tmp_path / "demo"))

    import json
    import os

    case = json.loads(open(os.path.join(case_dir, "case.json"), encoding="utf-8").read())
    assert case["status"] == "ready"
    assert len(case["packets"]) == len(demo_case.PEOPLE)
    # Matching is by identity, so every packet must carry one.
    assert all(p["ocrIdentity"]["cccd"] for p in case["packets"])
    assert all(p["matchedBy"] == "cccd" for p in case["packets"])

    manifest = json.loads(
        open(os.path.join(case_dir, "packets", "0", "manifest.json"), encoding="utf-8").read()
    )
    kinds = [d["kind"] for d in manifest["docs"]]
    assert "contract" in kinds and "bbnt" in kinds
    assert all(k in {"id_front", "id_back", "contract", "commitment", "pit",
                     "bbnt", "appendix"} for k in kinds)

    # Every page a doc claims must exist on disk, or the viewer shows nothing.
    for doc in manifest["docs"]:
        for page in doc["pages"]:
            assert os.path.isfile(os.path.join(case_dir, "packets", "0",
                                               os.path.basename(page["src"])))


def test_built_case_contains_no_real_looking_identity(tmp_path):
    """The whole point. Every number is sequential from a fabricated base."""
    case_dir = demo_case.build(str(tmp_path / "demo"))
    import pathlib
    import re

    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in pathlib.Path(case_dir).rglob("*.json")
    )
    for number in re.findall(r"\b\d{9,13}\b", text):
        assert number.startswith(("0011", "1900")), f"unexpected identifier {number}"


def test_the_demo_shows_a_mismatch_an_absence_and_something_pending(tmp_path):
    """A demo where every cell is green teaches nobody anything. Assert the three
    states a reviewer needs to see actually occur."""
    import json
    import os

    case_dir = demo_case.build(str(tmp_path / "demo"))

    def manifest(index):
        path = os.path.join(case_dir, "packets", str(index), "manifest.json")
        return json.loads(open(path, encoding="utf-8").read())

    # A red cell: the documents disagree with the bảng kê on one account number.
    mismatch = manifest(demo_case._MISMATCH_PACKET)
    account = next(f for f in mismatch["fields"] if f["key"] == "tk")
    assert account["sources"], "the mismatch packet must still have a reading"
    assert all(s["value"] != account["expected"] for s in account["sources"])

    # An absence: one packet has no appendix at all.
    absent = manifest(demo_case._NO_APPENDIX_PACKET)
    assert "appendix" not in [d["kind"] for d in absent["docs"]]

    # Something pending: one field was never extracted.
    pending = manifest(demo_case._UNEXTRACTED_PACKET)
    date = next(f for f in pending["fields"] if f["key"] == "ngaysinh")
    assert date["sources"] == []


def test_headings_are_actually_larger_than_body_text():
    """`ImageFont.load_default()` ignores `size`, so a fallback chain that misses
    every installed font renders the whole page at one unreadable size -- and
    nothing else notices, because the PNG is still a valid PNG."""
    small = demo_case._font(11).getbbox("HỢP ĐỒNG")
    large = demo_case._font(44).getbbox("HỢP ĐỒNG")

    assert large[2] > small[2] * 2, "the font is ignoring the requested size"


def test_the_signature_block_uses_the_phrase_the_corpus_uses():
    """`Bên Cung Ứng Dịch Vụ`, not `Cung Cấp`: the reader anchors on the former
    (ocr_extract._PARTY_B_HEADER), so a demo drawing the latter would not be
    found by the very code it exists to exercise."""
    import inspect

    source = inspect.getsource(demo_case.page_png)
    assert "CUNG ỨNG" in source
    assert "CUNG CẤP" not in source
