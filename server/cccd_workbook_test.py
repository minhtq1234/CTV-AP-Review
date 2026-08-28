import base64
import os
import zipfile

import pytest

import cccd_workbook
from cccd_workbook import Anchor, CccdWorkbookError, extract_drawings


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII="
)


def _jpeg():
    return (
        b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01"
        b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


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
    with zipfile.ZipFile(path, "w") as archive:
        workbook_sheets = []
        workbook_rels = []
        for index, (sheet_name, images) in enumerate(sheets, start=1):
            workbook_sheets.append(
                f'<sheet name="{sheet_name}" sheetId="{index}" r:id="rId{index}"/>'
            )
            workbook_rels.append((
                f"rId{index}",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                f"worksheets/sheet{index}.xml",
                "",
            ))
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<drawing r:id="rIdDrawing"/></worksheet>',
            )
            archive.writestr(
                f"xl/worksheets/_rels/sheet{index}.xml.rels",
                _rels([(
                    "rIdDrawing",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing",
                    f"../drawings/drawing{index}.xml",
                    "",
                )]),
            )

            anchors = []
            drawing_rels = []
            for rel_id, media_path, anchor, image in images:
                if len(anchor) == 4:
                    from_row, from_col, to_row, to_col = anchor
                    from_row_offset = from_col_offset = 0
                    to_row_offset = to_col_offset = 0
                    include_offsets = False
                else:
                    (
                        from_row,
                        from_col,
                        to_row,
                        to_col,
                        from_row_offset,
                        from_col_offset,
                        to_row_offset,
                        to_col_offset,
                    ) = anchor
                    include_offsets = True
                anchors.append(
                    '<xdr:twoCellAnchor><xdr:from>'
                    f'<xdr:col>{from_col}</xdr:col>'
                    + (
                        f'<xdr:colOff>{from_col_offset}</xdr:colOff>'
                        if include_offsets else ""
                    )
                    + f'<xdr:row>{from_row}</xdr:row>'
                    + (
                        f'<xdr:rowOff>{from_row_offset}</xdr:rowOff>'
                        if include_offsets else ""
                    )
                    + '</xdr:from><xdr:to>'
                    + f'<xdr:col>{to_col}</xdr:col>'
                    + (
                        f'<xdr:colOff>{to_col_offset}</xdr:colOff>'
                        if include_offsets else ""
                    )
                    + f'<xdr:row>{to_row}</xdr:row>'
                    + (
                        f'<xdr:rowOff>{to_row_offset}</xdr:rowOff>'
                        if include_offsets else ""
                    )
                    + '</xdr:to><xdr:pic><xdr:blipFill>'
                    + f'<a:blip r:embed="{rel_id}"/>'
                    + '</xdr:blipFill></xdr:pic></xdr:twoCellAnchor>'
                )
                drawing_rels.append((
                    rel_id,
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                    f"../media/{media_path.rsplit('/', 1)[-1]}",
                    "",
                ))
                archive.writestr(media_path, image)
            archive.writestr(
                f"xl/drawings/drawing{index}.xml",
                '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"{''.join(anchors)}</xdr:wsDr>",
            )
            archive.writestr(
                f"xl/drawings/_rels/drawing{index}.xml.rels",
                _rels(drawing_rels),
            )

        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(workbook_sheets)}</sheets></workbook>",
        )
        archive.writestr("xl/_rels/workbook.xml.rels", _rels(workbook_rels))


def _replace_zip_part(path, part_name, content):
    replacement = path.with_suffix(".replacement.xlsx")
    with zipfile.ZipFile(path) as old, zipfile.ZipFile(replacement, "w") as new:
        for info in old.infolist():
            new.writestr(
                info,
                content if info.filename == part_name else old.read(info.filename),
            )
    replacement.replace(path)


def test_anchor_offsets_default_to_zero():
    anchor = Anchor("Cards", 1, 2, 10, 3)

    assert (
        anchor.from_row_offset,
        anchor.from_col_offset,
        anchor.to_row_offset,
        anchor.to_col_offset,
    ) == (0, 0, 0, 0)


def test_extract_drawings_preserves_full_anchor_offsets(tmp_path):
    book = tmp_path / "offsets.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [(
            "rId1",
            "xl/media/image1.png",
            (7, 2, 18, 4, 111, 222, 333, 444),
            _PNG,
        )])],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))
    assert result.drawings[0].anchor == Anchor(
        "Cards",
        7,
        2,
        18,
        4,
        from_row_offset=111,
        from_col_offset=222,
        to_row_offset=333,
        to_col_offset=444,
        # The sheet declares no row heights, so every row is Excel's 15pt
        # default: 7 * 15 * 12700 + 111, and 18 * 15 * 12700 + 333.
        top_emu=1333611,
        bottom_emu=3429333,
    )


def test_extract_drawings_follows_relationships_not_media_names(tmp_path):
    book = tmp_path / "cards.xlsx"
    _write_synthetic_xlsx(
        book,
        [
            ("Cards A", [
                ("rId9", "xl/media/image20.png", (1, 0, 10, 1), _PNG),
                ("rId2", "xl/media/image3.png", (1, 1, 10, 2), _PNG),
            ]),
            ("Cards B", [
                ("rId4", "xl/media/image1.jpeg", (20, 0, 28, 1), _jpeg()),
            ]),
        ],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert result.drawing_instances == 3
    assert [
        (drawing.anchor.sheet, drawing.anchor.from_row, drawing.extension)
        for drawing in result.drawings
    ] == [
        ("Cards A", 1, "png"),
        ("Cards A", 1, "png"),
        ("Cards B", 20, "jpg"),
    ]
    assert all(os.path.isfile(drawing.stored_path) for drawing in result.drawings)


@pytest.mark.parametrize(
    ("target", "mode", "code"),
    [
        ("https://example.invalid/image.png", ' TargetMode="External"', "external-relationship"),
        ("../../../outside.png", "", "invalid-target"),
    ],
)
def test_unsafe_image_relationship_is_reported(tmp_path, target, mode, code):
    book = tmp_path / "unsafe.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [("rId1", "xl/media/image1.png", (0, 0, 1, 1), _PNG)])],
    )
    _replace_zip_part(
        book,
        "xl/drawings/_rels/drawing1.xml.rels",
        _rels([(
            "rId1",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            target,
            mode,
        )]),
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert [issue.code for issue in result.issues] == [code]
    assert result.drawings == []


@pytest.mark.parametrize(
    ("limit_name", "code"),
    [
        ("MAX_ARCHIVE_MEMBERS", "archive-member-limit"),
        ("MAX_ARCHIVE_MEMBER_BYTES", "archive-member-too-large"),
        ("MAX_ARCHIVE_UNCOMPRESSED_BYTES", "archive-uncompressed-too-large"),
    ],
)
def test_archive_limits_are_hard_failures(tmp_path, monkeypatch, limit_name, code):
    book = tmp_path / "bounded.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [("rId1", "xl/media/image1.png", (0, 0, 1, 1), _PNG)])],
    )
    monkeypatch.setattr(cccd_workbook, limit_name, 1)

    with pytest.raises(CccdWorkbookError, match=code):
        extract_drawings(str(book), str(tmp_path / "out"))


def test_total_image_budget_is_enforced_before_writing_next_image(
    tmp_path,
    monkeypatch,
):
    book = tmp_path / "budget.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [
            ("rId1", "xl/media/image1.png", (0, 0, 1, 1), _PNG),
            ("rId2", "xl/media/image2.png", (1, 0, 2, 1), _PNG),
        ])],
    )
    monkeypatch.setattr(cccd_workbook, "MAX_TOTAL_IMAGE_BYTES", len(_PNG))

    with pytest.raises(CccdWorkbookError, match="total-image-too-large"):
        extract_drawings(str(book), str(tmp_path / "out"))

    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        "drawing-0001.png",
    ]


def _one_cell_drawing(rel_id, from_col, from_row):
    """A picture anchored at one cell with a pixel extent -- no <to> element.

    This is what the converted July workbook emits, and what the extractor used
    to skip silently, reporting "no supported images" for a file full of them.
    """
    return (
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/'
        'spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/'
        'drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships">'
        '<xdr:oneCellAnchor><xdr:from>'
        f'<xdr:col>{from_col}</xdr:col><xdr:colOff>9525</xdr:colOff>'
        f'<xdr:row>{from_row}</xdr:row><xdr:rowOff>19050</xdr:rowOff>'
        '</xdr:from><xdr:ext cx="2857500" cy="1809750"/>'
        '<xdr:pic><xdr:blipFill>'
        f'<a:blip r:embed="{rel_id}"/>'
        '</xdr:blipFill></xdr:pic></xdr:oneCellAnchor></xdr:wsDr>'
    )


def test_one_cell_anchored_pictures_are_extracted(tmp_path):
    book = tmp_path / "one-cell.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [("rId1", "xl/media/image1.png", (3, 2, 4, 3), _PNG)])],
    )
    _replace_zip_part(
        book,
        "xl/drawings/drawing1.xml",
        _one_cell_drawing("rId1", from_col=2, from_row=3),
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert len(result.drawings) == 1
    anchor = result.drawings[0].anchor
    assert (anchor.sheet, anchor.from_row, anchor.from_col) == ("Cards", 3, 2)
    # No "to" cell exists, so the picture spans its own cell.
    assert (anchor.to_row, anchor.to_col) == (4, 3)
    assert (anchor.from_row_offset, anchor.from_col_offset) == (19050, 9525)
    assert (anchor.to_row_offset, anchor.to_col_offset) == (0, 0)


def test_one_and_two_cell_anchors_coexist_in_one_sheet(tmp_path):
    book = tmp_path / "mixed.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [
            ("rId1", "xl/media/image1.png", (0, 0, 1, 1), _PNG),
            ("rId2", "xl/media/image2.png", (5, 0, 6, 1), _PNG),
        ])],
    )
    two_cell = (
        '<xdr:twoCellAnchor><xdr:from>'
        '<xdr:col>0</xdr:col><xdr:row>0</xdr:row></xdr:from><xdr:to>'
        '<xdr:col>1</xdr:col><xdr:row>1</xdr:row></xdr:to>'
        '<xdr:pic><xdr:blipFill><a:blip r:embed="rId1"/>'
        '</xdr:blipFill></xdr:pic></xdr:twoCellAnchor>'
    )
    mixed = _one_cell_drawing("rId2", from_col=0, from_row=5).replace(
        "<xdr:oneCellAnchor>", two_cell + "<xdr:oneCellAnchor>", 1
    )
    _replace_zip_part(book, "xl/drawings/drawing1.xml", mixed)

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert len(result.drawings) == 2
    assert [d.anchor.from_row for d in result.drawings] == [0, 5]


# --- image dimensions ------------------------------------------------------

def _jpeg_bytes(width: int, height: int) -> bytes:
    """A minimal JPEG whose SOF0 declares `height` lines x `width` samples."""
    sof = (b"\xff\xc0" + (11).to_bytes(2, "big") + b"\x08"
           + height.to_bytes(2, "big") + width.to_bytes(2, "big")
           + b"\x03\x01\x11\x00")
    return b"\xff\xd8" + sof + b"\xff\xd9"


def test_jpeg_size_returns_width_then_height_not_header_order():
    """SOF declares HEIGHT before WIDTH; returning header order transposes.

    This transposed every CCCD card in the manifest -- 280x419 recorded for a
    419x280 image -- and since the evidence viewer maps a field's bbox through
    those dimensions, every card highlight landed in the wrong place.
    """
    from cccd_workbook import _jpeg_size
    assert _jpeg_size(_jpeg_bytes(width=622, height=288)) == (622, 288)
    assert _jpeg_size(_jpeg_bytes(width=288, height=622)) == (288, 622)


def test_jpeg_size_matches_a_landscape_card_shape():
    # Real CCCD cards are landscape; the bug was invisible on a square image.
    from cccd_workbook import _jpeg_size
    width, height = _jpeg_size(_jpeg_bytes(width=505, height=319))
    assert width > height, "a landscape card must not come back portrait"


def test_png_size_was_already_correct():
    # PNG's IHDR really does put width first, so only the JPEG path was wrong.
    import struct, zlib
    from cccd_workbook import _png_size
    def chunk(tag, data):
        return (len(data).to_bytes(4, "big") + tag + data
                + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))
    w, h = 622, 288
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * w for _ in range(h))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    assert _png_size(png) == (w, h)


def test_row_heights_come_from_the_sheet_not_a_constant():
    """The measure is only as good as the row heights behind it. On the real
    combined workbook the image rows are 136.5pt while the sheet's own declared
    default is 15pt, so assuming the default puts every drawing in the wrong
    place and nothing pairs."""
    from cccd_workbook import EMU_PER_POINT, RowGeometry, _row_top_emu

    default = round(15.0 * EMU_PER_POINT)
    tall = round(136.5 * EMU_PER_POINT)
    geometry = RowGeometry.build(default, {1: tall, 2: tall})

    assert _row_top_emu(0, geometry) == 0
    assert _row_top_emu(1, geometry) == default
    assert _row_top_emu(2, geometry) == default + tall
    assert _row_top_emu(3, geometry) == default + tall * 2


def test_every_extracted_drawing_carries_geometry(tmp_path):
    """The row-span fallback in `_vertical_overlap_ratio` must be unreachable on
    the real path: if extraction ever stopped populating this, pairing would
    silently revert to the measure that could not size a single-row drawing."""
    book = tmp_path / "geometry.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [
            ("rId1", "xl/media/image1.png", (3, 1, 3, 2, 0, 0, 0, 0), _PNG),
            ("rId2", "xl/media/image2.png", (3, 3, 3, 4, 0, 0, 0, 0), _PNG),
        ])],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert len(result.drawings) == 2
    for drawing in result.drawings:
        assert drawing.anchor.top_emu is not None
        assert drawing.anchor.bottom_emu is not None


def test_a_one_cell_anchor_is_as_tall_as_its_declared_extent(tmp_path):
    """A oneCellAnchor states its real height in `ext/@cy`. Deriving the box
    from the synthesised `to_row` instead describes the row the picture starts
    in -- on the July workbook, whose every anchor is this shape, that made all
    84 boxes an identical 171450 EMU against real heights of 952500-1524000,
    and pairing then worked only because the fabrications happened to be equal.
    """
    from cccd_workbook import EMU_PER_POINT

    book = tmp_path / "one-cell-extent.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [("rId1", "xl/media/image1.png", (3, 2, 4, 3), _PNG)])],
    )
    _replace_zip_part(
        book,
        "xl/drawings/drawing1.xml",
        _one_cell_drawing("rId1", from_col=2, from_row=3),
    )

    anchor = extract_drawings(str(book), str(tmp_path / "out")).drawings[0].anchor

    default = round(15.0 * EMU_PER_POINT)
    assert anchor.top_emu == 3 * default + 19050
    # cy="1809750" from the fixture -- nine times the 15pt row it sits in.
    assert anchor.bottom_emu == anchor.top_emu + 1809750


def test_row_geometry_reads_declared_heights_off_the_sheet(tmp_path):
    """The half of the fix that reads the XML. Without it every row is the 15pt
    default, which on the real workbook (136.5pt image rows) puts every drawing
    in the wrong place and pairs nothing -- so this must be covered directly."""
    import zipfile as _zipfile

    from cccd_workbook import (
        EMU_PER_POINT,
        _ExtractionByteBudget,
        MAX_ARCHIVE_UNCOMPRESSED_BYTES,
        _row_geometry,
    )

    book = tmp_path / "heights.xlsx"
    with _zipfile.ZipFile(book, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">'
            '<sheetFormatPr defaultRowHeight="20"/>'
            '<sheetData>'
            '<row r="2" ht="100" customHeight="1"/>'
            '<row r="3" ht="50" customHeight="1"/>'
            '<row r="4"/>'
            '</sheetData></worksheet>',
        )

    with _zipfile.ZipFile(book) as archive:
        geometry = _row_geometry(
            archive,
            "xl/worksheets/sheet1.xml",
            _ExtractionByteBudget(MAX_ARCHIVE_UNCOMPRESSED_BYTES),
        )

    default = round(20.0 * EMU_PER_POINT)
    assert geometry.default == default
    # Row indices are 0-based here; the XML's r attribute is 1-based.
    assert geometry.top(0) == 0
    assert geometry.top(1) == default
    assert geometry.top(2) == default + round(100.0 * EMU_PER_POINT)
    assert geometry.top(3) == (
        default + round(100.0 * EMU_PER_POINT) + round(50.0 * EMU_PER_POINT)
    )
    # A row with no explicit height falls back to the sheet default.
    assert geometry.top(4) - geometry.top(3) == default
