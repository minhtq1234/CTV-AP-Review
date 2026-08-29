"""Build one synthetic, already-processed case for demos and for developing the
screens against.

Deliberately NOT run through the reader: see the plan's "decision that keeps
this small". Nothing here is OCR'd, so the page images only have to look like
paperwork, and the values come from the manifest this module writes.

Everything is fabricated. No real contractor appears anywhere in it.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from test_fixtures.combined_workbook import PEOPLE as _IDENTITIES

#: The demo-only columns, in the same order as the shared identity series. Kept
#: separate from the identities themselves so this module cannot drift into a
#: second set of fabricated people: the name, CCCD and MST always come from
#: `combined_workbook.PEOPLE`, and only the payment detail is added here.
_PAYMENT = [
    {"stt": 1, "tk": "1900000001", "dob": "01/01/1990",
     "gender": "Nam", "gross": 8_000_000, "pit": 0,       "net": 8_000_000},
    {"stt": 2, "tk": "1900000002", "dob": "02/02/1991",
     "gender": "Nữ",  "gross": 8_888_889, "pit": 888_889, "net": 8_000_000},
    {"stt": 3, "tk": "1900000003", "dob": "03/03/1992",
     "gender": "Nam", "gross": 4_400_000, "pit": 0,       "net": 4_400_000},
]

#: Fabricated people. Sequential ID numbers, obviously-synthetic names, so no
#: real identity can be mistaken for one of these.
PEOPLE = [
    {"name": name, "cccd": cccd, "mst": mst, **payment}
    for (name, cccd, mst), payment in zip(_IDENTITIES, _PAYMENT)
]


def _font(size: int) -> ImageFont.ImageFont:
    """A font that renders at the requested size.

    Pillow's default font ignores `size`, which makes every page look the same
    and the headings unreadable. Try the DejaVu that ships with most Pillow
    installs first, then fall back rather than failing the build.
    """
    for name in ("DejaVuSans.ttf", "Arial Unicode.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def page_png(heading: str, lines: list[str], *, width: int, height: int) -> bytes:
    """One page of fabricated paperwork as PNG bytes.

    Deterministic: same arguments, same bytes. A fixture that changes on every
    build is not a fixture.
    """
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    margin = max(24, width // 14)
    draw.text((margin, margin), heading, fill="black", font=_font(max(14, width // 32)))
    draw.line([(margin, margin + height // 22), (width - margin, margin + height // 22)],
              fill="black", width=2)

    y = margin + height // 16
    body = _font(max(11, width // 55))
    for line in lines:
        draw.text((margin, y), line, fill="black", font=body)
        y += height // 26

    # A signature block at the foot, so the six signature criteria have
    # something plausible to point at once they learn how.
    draw.text((margin, height - margin - height // 12), "BÊN CUNG CẤP DỊCH VỤ",
              fill="black", font=body)
    draw.text((width // 2, height - margin - height // 12), "ĐẠI DIỆN VNG",
              fill="black", font=body)

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=False)
    return out.getvalue()


#: The documents each packet carries, as (kind, label, page count). Matches the
#: closed EvidenceKind set in src/ctv/types.ts.
_DOCS = [
    ("contract", "Hợp đồng dịch vụ", 2),
    ("bbnt", "Biên bản nghiệm thu", 1),
    ("appendix", "Phụ lục KPI", 1),
    ("pit", "Tra cứu thuế", 1),
    ("id_front", "CCCD mặt trước", 1),
    ("id_back", "CCCD mặt sau", 1),
]

#: Field metadata, copied from a real manifest rather than invented, so the
#: reviewer groups and comparators behave exactly as they do on a real case.
_FIELDS = [
    ("hoten", "Họ tên", "Danh tính", "person", "name"),
    ("cccd", "Số CCCD", "Danh tính", "text", "cccd"),
    ("mst", "Mã số thuế", "Danh tính", "text", "mst"),
    ("tk", "Số tài khoản", "Ngân hàng", "text", "tk"),
    ("ngaysinh", "Ngày sinh", "Danh tính", "date", "dob"),
    ("phi", "Phí dịch vụ", "Thanh toán", "number", "gross"),
]

_PAGE_WIDTH, _PAGE_HEIGHT = 1000, 1400

#: The packet that gets a wrong account number, so the demo has a red cell.
_MISMATCH_PACKET = 1
#: The packet with no appendix, so `na` appears rather than every cell green.
_NO_APPENDIX_PACKET = 2
#: The packet whose date was never extracted, so `pending` appears.
_UNEXTRACTED_PACKET = 0


def _docs_for(index: int) -> list[tuple[str, str, int]]:
    return [
        entry for entry in _DOCS
        if not (index == _NO_APPENDIX_PACKET and entry[0] == "appendix")
    ]


def _value_for(person: dict, field_key: str, source_key: str, index: int) -> str:
    """What the documents say. Usually the roster value; deliberately not on the
    one packet that exists to show a mismatch."""
    raw = person[source_key]
    text = f"{raw:,}".replace(",", ".") if isinstance(raw, int) else str(raw)
    if field_key == "tk" and index == _MISMATCH_PACKET:
        # One digit out: the reviewer should see a red cell and be able to say
        # why without reading the whole page.
        return text[:-1] + ("0" if text[-1] != "0" else "1")
    return text


def build(target_dir: str, *, case_id: str | None = None) -> str:
    """Write a whole already-processed case, ready to browse, and return its path.

    Shaped from a real ingested case rather than from a specification: case.json
    also carries `cccdWorkbook`, `purchaseTotal` and a per-packet `review`, and
    every packet carries both an `ocrIdentity` and a `rosterIdentity`.
    """
    import json
    import os

    os.makedirs(target_dir, exist_ok=True)
    packets = []

    for index, person in enumerate(PEOPLE):
        packet_dir = os.path.join(target_dir, "packets", str(index))
        os.makedirs(packet_dir, exist_ok=True)

        docs, page_number = [], 0
        for kind, label, page_count in _docs_for(index):
            pages = []
            for offset in range(page_count):
                name = f"pg{page_number}.png"
                with open(os.path.join(packet_dir, name), "wb") as handle:
                    handle.write(page_png(
                        label.upper(),
                        [
                            f"Họ và tên: {person['name']}",
                            f"Số CCCD: {person['cccd']}",
                            f"Mã số thuế: {person['mst']}",
                            f"Số tài khoản: {person['tk']}",
                            f"Trang {offset + 1}/{page_count}",
                        ],
                        width=_PAGE_WIDTH,
                        height=_PAGE_HEIGHT,
                    ))
                pages.append({
                    "src": name,
                    "width": _PAGE_WIDTH,
                    "height": _PAGE_HEIGHT,
                })
                page_number += 1
            docs.append({
                "id": f"{kind}-0",
                "kind": kind,
                "label": label,
                "pages": pages,
            })

        readable = [d for d in docs if d["kind"] in {"contract", "bbnt"}]
        fields = []
        for field_key, label, group, kind, source_key in _FIELDS:
            expected = person[source_key]
            expected_text = (
                f"{expected:,}".replace(",", ".")
                if isinstance(expected, int) else str(expected)
            )
            sources = []
            # One field on one packet is left unextracted, so `pending` shows.
            if not (index == _UNEXTRACTED_PACKET and field_key == "ngaysinh"):
                for position, doc in enumerate(readable):
                    sources.append({
                        "docId": doc["id"],
                        "page": 0,
                        "value": _value_for(person, field_key, source_key, index),
                        "bbox": {
                            "x": 120,
                            "y": 220 + position * 60,
                            "width": 420,
                            "height": 38,
                        },
                        "confidence": 0.96,
                    })
            fields.append({
                "key": field_key,
                "label": label,
                "group": group,
                "check": "compare",
                "kind": kind,
                "expected": expected_text,
                "sources": sources,
            })

        with open(os.path.join(packet_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "id": f"demo-{index}",
                "name": person["name"],
                "product": "Danh Tướng 3Q",
                "heading": person["name"],
                "status": "pending",
                "exempt": False,
                "docs": docs,
                "fields": fields,
            }, handle, ensure_ascii=False, indent=2)

        packets.append({
            "index": index,
            "name": person["name"],
            "pages": [page_number * index, page_number * index + page_number - 1],
            "n_pages": page_number,
            "confidence": "green",
            "flags": [],
            "labels": [label for _, label, count in _docs_for(index) for _ in range(count)],
            "matchedBy": "cccd",
            "ocrIdentity": {"cccd": person["cccd"], "name": person["name"]},
            "rosterIdentity": {"cccd": person["cccd"], "name": person["name"]},
            "review": {"done": False, "fields": {}, "rejection": None, "overrides": {}},
        })

    with open(os.path.join(target_dir, "case.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "id": case_id or os.path.basename(target_dir.rstrip(os.sep)),
            "name": "demo.pdf",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "status": "ready",
            "pdfName": "demo.pdf",
            "rosterName": "demo-roster.xlsx",
            "cccdName": None,
            "summary": {
                "found": len(PEOPLE),
                "roster_n": len(PEOPLE),
                "matched": len(PEOPLE),
                "auto_merged": 0,
                "duplicate_identities": 0,
                "boundaries_snapped": len(PEOPLE),
                "boundaries_offset": 0,
                "boundaries_reason": "",
                "boundaries_inferred": 0,
                "boundaries_inserted": 0,
            },
            "cccdWorkbook": None,
            "purchaseTotal": None,
            "error": None,
            "packets": packets,
        }, handle, ensure_ascii=False, indent=2)

    return target_dir
