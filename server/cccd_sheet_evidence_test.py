"""Tests for `cccd_ingest.attach_sheet_evidence`.

The sheet screenshots were evidence the workbook always carried and nothing
could reach: classified at upload, then used only to keep themselves out of
the card candidate pool. On the combined template that left 25 tax lookups in
the file while #6 reported the document missing on all 25 packets.

Synthetic identity series only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import cccd_ingest


@dataclass(frozen=True)
class FakeAnchor:
    sheet: str
    center_row: int | None


@dataclass(frozen=True)
class FakeDrawing:
    id: str
    kind: str | None
    anchor: FakeAnchor
    stored_path: str = ""
    sha256: str = "a" * 64
    extension: str = "png"
    width: int = 600
    height: int = 380


HEADER = ("STT", "Họ và tên", "CCCD", "MST")

#: Two people. The MST sheet lists them in the OPPOSITE order to the roster,
#: which is the shape of the real workbook -- 17 of 25 positions disagreeing.
ROSTER = [
    ("BẢNG KÊ", None, None, None),
    HEADER,
    ("1", "NGUYEN VAN MOT", "001100000001", "0011000001"),
    ("2", "NGUYEN VAN HAI", "001100000002", "0011000002"),
]
MST_SHEET = [
    ("TRA CỨU MST", None, None, None),
    HEADER,
    ("1", "NGUYEN VAN HAI", "", "0011000002"),
    ("2", "NGUYEN VAN MOT", "", "0011000001"),
]

ROSTER_ROWS = [
    {"name": "NGUYEN VAN MOT", "cccd": "001100000001", "mst": "0011000001"},
    {"name": "NGUYEN VAN HAI", "cccd": "001100000002", "mst": "0011000002"},
]


def build_case(tmp_path, packets=2):
    """A case directory with `packets` manifests, and an extracted image each."""
    case_dir = tmp_path / "case"
    extracted = case_dir / "cccd-assets" / "extracted"
    extracted.mkdir(parents=True)
    manifest_paths = {}
    metas = []
    for index in range(packets):
        packet_dir = case_dir / "packets" / str(index)
        packet_dir.mkdir(parents=True)
        manifest = packet_dir / "manifest.json"
        manifest.write_text(json.dumps({
            "id": f"p{index}", "docs": [], "fields": [],
        }), encoding="utf-8")
        manifest_paths[index] = str(manifest)
        metas.append({
            "index": index,
            "rosterIdentity": {"cccd": ROSTER_ROWS[index]["cccd"]},
        })
    return case_dir, extracted, manifest_paths, metas


def image_at(extracted, name):
    path = extracted / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return str(path)


def docs_in(manifest_path):
    return json.loads(
        open(manifest_path, encoding="utf-8").read())["docs"]


class TestTaxScreenshots:
    def test_a_tax_screenshot_reaches_the_person_on_its_own_row(self, tmp_path):
        """The permuted sheet: row 2 of MST is the roster's SECOND person.

        A positional join would send it to packet 0.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 2),
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert refused == {}
        # packet 1, not packet 0
        assert set(written) == {1}
        assert docs_in(paths[0]) == []
        attached = docs_in(paths[1])
        assert len(attached) == 1
        assert attached[0]["kind"] == "pit"
        assert attached[0]["pages"][0]["width"] == 600

    def test_the_image_is_copied_into_the_packet(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        source = docs_in(paths[0])[0]["pages"][0]["src"]
        assert os.path.exists(source)
        assert os.path.dirname(source) == os.path.dirname(paths[0])

    def test_reading_the_same_workbook_twice_writes_one_document(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        for _ in range(3):
            cccd_ingest.attach_sheet_evidence(
                [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
                str(case_dir), paths,
            )
        assert len(docs_in(paths[0])) == 1

    def test_the_written_ids_are_owned_so_a_re_read_cleans_them(self, tmp_path):
        # Without this the reconciler would delete the documents the same
        # ingest had just written, since they are owned and would not appear
        # in the card keep-set.
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, _ = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        for ids in written.values():
            for doc_id in ids:
                assert cccd_ingest._is_owned_doc_id(doc_id)

        assert cccd_ingest.reconcile_owned_evidence(
            paths, str(case_dir), [], sheet_keep=written)
        assert len(docs_in(paths[0])) == 1

        # and with no keep-set, the same reconciler removes it
        assert cccd_ingest.reconcile_owned_evidence(paths, str(case_dir), [])
        assert docs_in(paths[0]) == []


class TestWhatIsNotAttached:
    def test_a_bank_screenshot_is_not_attached(self, tmp_path):
        """No criterion consumes one.

        `evaluate.DOC_KINDS` has no bank entry and `EvidenceKind` has no bank
        member, so a bank document would be storage with no reader.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "bank", FakeAnchor("CCCD", 2),
            stored_path=image_at(extracted, "bank0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"CCCD": ROSTER}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert written == {} and refused == {}
        assert docs_in(paths[0]) == []

    def test_a_card_is_left_to_the_card_path(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "card", FakeAnchor("CCCD", 2),
            stored_path=image_at(extracted, "card0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"CCCD": ROSTER}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert written == {} and refused == {}

    def test_a_person_with_no_packet_is_refused_not_guessed(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path, packets=1)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 2),  # the second person
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "no-packet-for-person"}

    def test_two_packets_claiming_one_identity_is_refused(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        metas[1]["rosterIdentity"] = dict(metas[0]["rosterIdentity"])
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "several-packets-for-person"}

    def test_an_asset_outside_the_case_directory_says_so(self, tmp_path):
        # Its own reason: folded into "attachment-failed" this reads as a disk
        # problem when it means the extraction directory is in the wrong place.
        case_dir, _, paths, metas = build_case(tmp_path)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(outside, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "asset-outside-case-dir"}

    def test_no_sheet_rows_refuses_rather_than_falling_back_to_position(
        self, tmp_path,
    ):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {}, ROSTER_ROWS, metas, str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "no-sheet-rows"}

    def test_nothing_to_do_costs_no_workbook_read(self, tmp_path):
        case_dir, _, paths, metas = build_case(tmp_path)
        written, refused = cccd_ingest.attach_sheet_evidence(
            [], {}, ROSTER_ROWS, metas, str(case_dir), paths,
        )
        assert written == {} and refused == {}
