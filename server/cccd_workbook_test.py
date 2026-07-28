import base64
import os
import struct
import zipfile
import zlib

import pytest

import cccd_workbook
from cccd_workbook import CccdWorkbookError, extract_drawings


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII="
)


def _png(_label):
    return _PNG


def _truncated_png():
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 8


def _png_with_scanlines(scanlines):
    def chunk(kind, content):
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


def _jpeg(_label):
    # Minimal JPEG with a baseline Start of Frame declaring a 1x1 image.
    return b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"


def _rels(items):
    body = "".join(
        f'<Relationship Id="{rel_id}" Type="{kind}" Target="{target}"{mode}/>'
        for rel_id, kind, target, mode in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{body}</Relationships>"
    )


def _write_synthetic_xlsx(path, sheets):
    """Write a PII-free OOXML fixture with one drawing part per worksheet."""
    with zipfile.ZipFile(path, "w") as archive:
        workbook_sheets = []
        workbook_rels = []
        for index, (sheet_name, images) in enumerate(sheets, start=1):
            workbook_sheets.append(
                f'<sheet name="{sheet_name}" sheetId="{index}" r:id="rId{index}"/>'
            )
            workbook_rels.append(
                (f"rId{index}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", f"worksheets/sheet{index}.xml", "")
            )
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<drawing r:id="rIdDrawing"/></worksheet>',
            )
            archive.writestr(
                f"xl/worksheets/_rels/sheet{index}.xml.rels",
                _rels([("rIdDrawing", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing", f"../drawings/drawing{index}.xml", "")]),
            )

            anchors = []
            drawing_rels = []
            for image_index, (rel_id, media_path, anchor, image) in enumerate(images, start=1):
                from_row, from_col, to_row, to_col = anchor
                anchors.append(
                    '<xdr:twoCellAnchor><xdr:from>'
                    f'<xdr:col>{from_col}</xdr:col><xdr:row>{from_row}</xdr:row>'
                    '</xdr:from><xdr:to>'
                    f'<xdr:col>{to_col}</xdr:col><xdr:row>{to_row}</xdr:row>'
                    '</xdr:to><xdr:pic><xdr:blipFill>'
                    f'<a:blip r:embed="{rel_id}"/>'
                    '</xdr:blipFill></xdr:pic></xdr:twoCellAnchor>'
                )
                drawing_rels.append((rel_id, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", f"../media/{media_path.rsplit('/', 1)[-1]}", ""))
                archive.writestr(media_path, image)
            archive.writestr(
                f"xl/drawings/drawing{index}.xml",
                '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"{''.join(anchors)}</xdr:wsDr>",
            )
            archive.writestr(f"xl/drawings/_rels/drawing{index}.xml.rels", _rels(drawing_rels))

        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(workbook_sheets)}</sheets></workbook>",
        )
        archive.writestr("xl/_rels/workbook.xml.rels", _rels(workbook_rels))


def test_extract_drawings_follows_relationships_not_media_names(tmp_path):
    book = tmp_path / "cards.xlsx"
    _write_synthetic_xlsx(
        book,
        sheets=[
            ("Cards A", [
                ("rId9", "xl/media/image20.png", (1, 0, 10, 1), _png("front-a")),
                ("rId2", "xl/media/image3.png", (1, 1, 10, 2), _png("back-a")),
            ]),
            ("Cards B", [
                ("rId4", "xl/media/image1.jpeg", (20, 0, 28, 1), _jpeg("front-b")),
            ]),
        ],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert result.drawing_instances == 3
    assert [(d.anchor.sheet, d.anchor.from_row, d.extension) for d in result.drawings] == [
        ("Cards A", 1, "png"),
        ("Cards A", 1, "png"),
        ("Cards B", 20, "jpg"),
    ]
    assert all(os.path.isfile(d.stored_path) for d in result.drawings)


def _replace_zip_part(path, part_name, content):
    replacement = path.with_suffix(".replacement.xlsx")
    with zipfile.ZipFile(path) as old, zipfile.ZipFile(replacement, "w") as new:
        for info in old.infolist():
            new.writestr(info, content if info.filename == part_name else old.read(info.filename))
    replacement.replace(path)


def _replace_zip_part_compressed(path, part_name, content):
    replacement = path.with_suffix(".compressed-replacement.xlsx")
    with zipfile.ZipFile(path) as old, zipfile.ZipFile(
        replacement,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as new:
        for info in old.infolist():
            new.writestr(
                info.filename,
                content if info.filename == part_name else old.read(info.filename),
            )
    replacement.replace(path)


def _malicious_or_invalid_xlsx(tmp_path, fixture):
    book = tmp_path / f"{fixture}.xlsx"
    if fixture == "unsupported-gif":
        _write_synthetic_xlsx(book, [("Cards", [("rId1", "xl/media/image1.gif", (0, 0, 1, 1), b"GIF89a")])])
        return book
    if fixture == "truncated-png":
        _write_synthetic_xlsx(book, [("Cards", [("rId1", "xl/media/image1.png", (0, 0, 1, 1), _truncated_png())])])
        return book
    if fixture == "png-excess-output":
        _write_synthetic_xlsx(book, [("Cards", [(
            "rId1", "xl/media/image1.png", (0, 0, 1, 1),
            _png_with_scanlines(b"\x00\xff\xff\xff\xffunexpected"),
        )])])
        return book

    _write_synthetic_xlsx(book, [("Cards", [("rId1", "xl/media/image1.png", (0, 0, 1, 1), _png("safe"))])])
    if fixture == "external-image-rel":
        _replace_zip_part(
            book,
            "xl/drawings/_rels/drawing1.xml.rels",
            _rels([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "https://example.invalid/image.png", ' TargetMode="External"')]),
        )
    elif fixture == "path-traversal-rel":
        _replace_zip_part(
            book,
            "xl/drawings/_rels/drawing1.xml.rels",
            _rels([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "../../../outside.png", "")]),
        )
    elif fixture == "malformed-drawing":
        _replace_zip_part(book, "xl/drawings/drawing1.xml", "<xdr:wsDr")
    elif fixture == "malformed-anchor":
        _replace_zip_part(
            book,
            "xl/drawings/drawing1.xml",
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<xdr:twoCellAnchor><xdr:from><xdr:col>0</xdr:col></xdr:from>'
            '<xdr:to><xdr:col>1</xdr:col><xdr:row>1</xdr:row></xdr:to>'
            '<xdr:pic><xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill></xdr:pic>'
            '</xdr:twoCellAnchor></xdr:wsDr>',
        )
    else:
        raise AssertionError(f"unknown fixture: {fixture}")
    return book


@pytest.mark.parametrize("fixture, code", [
    ("external-image-rel", "external-relationship"),
    ("path-traversal-rel", "invalid-target"),
    ("unsupported-gif", "unsupported-media"),
    ("truncated-png", "unsupported-media"),
    ("png-excess-output", "unsupported-media"),
    ("malformed-drawing", "malformed-drawing"),
    ("malformed-anchor", "malformed-drawing"),
])
def test_invalid_drawing_is_reported_without_path_access(tmp_path, fixture, code):
    book = _malicious_or_invalid_xlsx(tmp_path, fixture)

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert any(issue.code == code for issue in result.issues)
    assert not any(".." in drawing.stored_path for drawing in result.drawings)


def test_drawing_ids_stay_unique_after_an_invalid_instance(tmp_path):
    book = tmp_path / "mixed.xlsx"
    _write_synthetic_xlsx(
        book,
        [
            ("Cards A", [
                ("rId1", "xl/media/image1.png", (0, 0, 1, 1), _png("first")),
                ("rId2", "xl/media/image2.png", (1, 0, 2, 1), _png("second")),
            ]),
            ("Cards B", [("rId1", "xl/media/image3.png", (2, 0, 3, 1), _png("third"))]),
        ],
    )
    _replace_zip_part(
        book,
        "xl/drawings/_rels/drawing1.xml.rels",
        _rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "https://example.invalid/image.png", ' TargetMode="External"'),
            ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "../media/image2.png", ""),
        ]),
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert [drawing.id for drawing in result.drawings] == ["drawing-0002", "drawing-0003"]
    assert len({drawing.stored_path for drawing in result.drawings}) == 2


def test_png_with_the_expected_scanline_payload_is_accepted(tmp_path):
    book = tmp_path / "valid-png.xlsx"
    _write_synthetic_xlsx(book, [("Cards", [(
        "rId1", "xl/media/image1.png", (0, 0, 1, 1),
        _png_with_scanlines(b"\x00\xff\xff\xff\xff"),
    )])])

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert [(drawing.width, drawing.height) for drawing in result.drawings] == [(1, 1)]
    assert result.issues == []


def _one_image_book(tmp_path, *, count=1):
    book = tmp_path / "limits.xlsx"
    images = [
        (f"rId{index}", f"xl/media/image{index}.png", (index, 0, index + 1, 1), _png(str(index)))
        for index in range(1, count + 1)
    ]
    _write_synthetic_xlsx(book, [("Cards", images)])
    return book


def test_workbook_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_WORKBOOK_BYTES", 1)

    with pytest.raises(CccdWorkbookError, match="workbook-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_archive_member_count_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(CccdWorkbookError, match="archive-member-limit"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_archive_member_size_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_ARCHIVE_MEMBER_BYTES", 1)

    with pytest.raises(CccdWorkbookError, match="archive-member-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_archive_total_uncompressed_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(CccdWorkbookError, match="archive-uncompressed-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


@pytest.mark.parametrize(
    "part_name",
    [
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/worksheets/sheet1.xml",
        "xl/worksheets/_rels/sheet1.xml.rels",
        "xl/drawings/drawing1.xml",
        "xl/drawings/_rels/drawing1.xml.rels",
    ],
)
def test_compressed_oversized_xml_parts_are_bounded(
    tmp_path,
    monkeypatch,
    part_name,
):
    book = _one_image_book(tmp_path)
    oversized_xml = b"<root>" + (b"x" * (1024 * 1024)) + b"</root>"
    _replace_zip_part_compressed(book, part_name, oversized_xml)
    with zipfile.ZipFile(book) as archive:
        info = archive.getinfo(part_name)
        assert info.file_size > 1024 * 1024
        assert info.compress_size < 2048
    monkeypatch.setattr(cccd_workbook, "MAX_XML_BYTES", 1024)

    with pytest.raises(CccdWorkbookError, match="xml-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_default_limits_match_the_spike_ceilings():
    assert cccd_workbook.MAX_WORKBOOK_BYTES == 100 * 1024 * 1024
    assert cccd_workbook.MAX_DRAWINGS == 500
    assert cccd_workbook.MAX_IMAGE_BYTES == 25 * 1024 * 1024
    assert cccd_workbook.MAX_TOTAL_IMAGE_BYTES == 500 * 1024 * 1024
    assert cccd_workbook.MAX_PIXELS == 40_000_000


def test_drawing_count_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path, count=2)
    monkeypatch.setattr(cccd_workbook, "MAX_DRAWINGS", 1)

    with pytest.raises(CccdWorkbookError, match="drawing-limit"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_drawing_count_limit_stops_before_later_anchor_is_decoded(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path, count=2)
    monkeypatch.setattr(cccd_workbook, "MAX_DRAWINGS", 1)
    original = cccd_workbook._anchor_value
    calls = 0

    def reject_later_anchor(*args):
        nonlocal calls
        calls += 1
        if calls > 4:
            raise AssertionError("later anchor was decoded after drawing limit")
        return original(*args)

    monkeypatch.setattr(cccd_workbook, "_anchor_value", reject_later_anchor)

    with pytest.raises(CccdWorkbookError, match="drawing-limit"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_per_image_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_IMAGE_BYTES", 1)

    with pytest.raises(CccdWorkbookError, match="image-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_total_image_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path, count=2)
    monkeypatch.setattr(cccd_workbook, "MAX_TOTAL_IMAGE_BYTES", 1)

    with pytest.raises(CccdWorkbookError, match="total-image-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_pixel_limit_is_a_hard_failure(tmp_path, monkeypatch):
    book = _one_image_book(tmp_path)
    monkeypatch.setattr(cccd_workbook, "MAX_PIXELS", 0)

    with pytest.raises(CccdWorkbookError, match="pixel-limit"):
        extract_drawings(str(book), str(tmp_path / "out"))
