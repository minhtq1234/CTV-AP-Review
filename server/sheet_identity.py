"""Which person an image on a workbook sheet belongs to.

The bank and tax screenshots on the combined template are evidence nobody can
reach: they are classified at upload (`workbook_layout.classify_image_columns`)
and then only ever used as a negative filter, to keep them out of the card
candidate pool. Nothing puts them in front of a criterion.

They cannot be matched the way a card is. A card carries a face and a number,
so `cccd_matching` reads an identity off the image itself; a tax lookup
screenshot has neither. The only thing that says whose it is, is where it sits.

Why position alone is not enough
--------------------------------
The obvious join -- "the image on sheet row N belongs to the person on roster
row N" -- is wrong on the real workbook, and wrong in the most expensive
direction. Measured on the combined template:

    sheet   same 25 people as the roster?   positions agreeing
    CCCD    yes                             25 / 25
    MST     yes                             8 / 25

The MST sheet lists the same people in a different order, and STT does not
rescue it -- each sheet renumbers 1..25 in its own sequence. A positional join
would therefore attach the wrong person's tax screenshot to 17 of 25 packets,
and a tax page has no face for a reviewer to notice is wrong. That is the same
class of error as a tax screenshot being attached as an ID card, which is what
this branch exists to fix.

**Anyone validating a positional join on the CCCD sheet sees 25 of 25 and
ships it.** The failure only shows on MST, which is the sheet that matters
here, because the tax screenshots are on it.

So position is used only WITHIN one sheet -- the image's centre row says which
row of *its own sheet* it sits on (`Anchor.center_row`) -- and the join across
to the roster is by identity, through the same `pipeline.match_roster` that
aligns a packet: CCCD, then personal MST, then name.
"""
from __future__ import annotations

from dataclasses import dataclass

import roster_checks


@dataclass(frozen=True)
class SheetPerson:
    """The identity written on one row of an image-bearing sheet."""

    row: int
    name: str = ""
    cccd: str = ""
    mst: str = ""

    @property
    def has_identity(self) -> bool:
        return bool(self.cccd or self.mst or self.name)


def people_by_row(rows: list[tuple] | list[list]) -> dict[int, SheetPerson]:
    """`{row index: SheetPerson}` for the numbered rows of one sheet.

    Keyed by the sheet's own 0-based row index, which is what
    `Anchor.center_row` counts in, so no offset arithmetic stands between a
    drawing and its row. `roster_checks.locate_columns` finds the columns --
    the same header matcher the bảng kê uses, because these sheets carry the
    same headers.
    """
    columns, first_data = roster_checks.locate_columns(list(rows))
    if not columns:
        return {}
    found: dict[int, SheetPerson] = {}
    for index in range(first_data, len(rows)):
        row = rows[index]
        if not row:
            continue
        head = str(row[0] if len(row) else "").strip()
        # Numbered rows only, exactly as `roster_checks.read_people` decides
        # what is a person and what is a title or a total.
        if not head.replace(".", "").strip().isdigit():
            continue

        def value(key: str) -> str:
            position = columns.get(key)
            if position is None or position >= len(row):
                return ""
            return str(row[position] or "").strip()

        person = SheetPerson(
            row=index,
            name=value("name"),
            cccd=value("cccd"),
            mst=value("mst"),
        )
        if person.has_identity:
            found[index] = person
    return found


def resolve(
    person: SheetPerson,
    by_cccd: dict[str, dict],
    by_name: dict[str, dict],
    by_mst: dict[str, dict],
) -> tuple[dict | None, str]:
    """`(roster row, how)` for a sheet person, or `(None, "unmatched")`.

    Delegates to `pipeline.match_roster` rather than reimplementing the key
    order: strongest identifier first, because the wrong-person error is the
    most expensive one this tool can make, and that reasoning is already
    written down there.
    """
    import pipeline

    return pipeline.match_roster(
        person.cccd, person.name, by_cccd, by_name,
        mst=person.mst, by_mst=by_mst,
    )


def attribute(
    drawings: list,
    sheet_rows: dict[str, list],
    by_cccd: dict[str, dict],
    by_name: dict[str, dict],
    by_mst: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, str]]:
    """`({drawing id: roster row}, {drawing id: why not})` for every drawing.

    A drawing is attributed only when its own sheet row carries an identity
    that resolves to exactly one roster row. Everything else is reported as a
    reason rather than guessed at: an unattributed screenshot shows a reviewer
    nothing, and a misattributed one shows them a lie.
    """
    people: dict[str, dict[int, SheetPerson]] = {}
    matched: dict[str, dict] = {}
    refused: dict[str, str] = {}

    for drawing in drawings:
        anchor = drawing.anchor
        sheet = anchor.sheet
        if sheet not in sheet_rows:
            refused[drawing.id] = "no-sheet-rows"
            continue
        if sheet not in people:
            people[sheet] = people_by_row(sheet_rows[sheet])
        if anchor.center_row is None:
            # Only when the sheet had no row geometry to measure against, in
            # which case `from_row` is all there is -- and it is ragged for 24
            # of 75 drawings on the real workbook, so it is not a fallback.
            refused[drawing.id] = "no-centre-row"
            continue
        person = people[sheet].get(anchor.center_row)
        if person is None:
            refused[drawing.id] = "no-person-on-row"
            continue
        row, how = resolve(person, by_cccd, by_name, by_mst)
        if row is None:
            refused[drawing.id] = f"unmatched-{how}"
            continue
        matched[drawing.id] = row
    return matched, refused
