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
