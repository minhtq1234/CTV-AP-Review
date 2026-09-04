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

import pytest

import cccd_ingest
from cccd_ingest import LeaveSheetEvidence, ReconcileSheetEvidence


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

    def _attach_one(self, tmp_path):
        case_dir, extracted, paths, metas = build_case(tmp_path)
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, _ = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
            str(case_dir), paths,
        )
        return case_dir, paths, written

    def test_a_re_read_that_did_not_write_it_removes_it(self, tmp_path):
        # The ingest DOES own these: it passes a keep-set, and a document not
        # in it is stale and goes.
        case_dir, paths, written = self._attach_one(tmp_path)
        assert len(docs_in(paths[0])) == 1

        assert cccd_ingest.reconcile_owned_evidence(
            paths, str(case_dir), [],
            sheet_keep=ReconcileSheetEvidence(written))
        assert len(docs_in(paths[0])) == 1

        assert cccd_ingest.reconcile_owned_evidence(
            paths, str(case_dir), [],
            sheet_keep=ReconcileSheetEvidence({}))
        assert docs_in(paths[0]) == []

    def test_reconciling_a_sheet_document_away_removes_its_image(
        self, tmp_path,
    ):
        """Dropping the document must take the file with it.

        `app.get_page` serves any matching filename out of the packet
        directory WITHOUT opening the manifest, so an orphaned
        `sheet-pit-....png` keeps returning that person's tax lookup -- their
        name and their MST -- to anyone who ever saw the URL. The unlink only
        ever looked at basenames starting `cccd-`, and sheet images start
        `sheet-`.
        """
        case_dir, paths, _ = self._attach_one(tmp_path)
        source = docs_in(paths[0])[0]["pages"][0]["src"]
        assert os.path.exists(source)
        packet_dir = os.path.dirname(paths[0])

        assert cccd_ingest.reconcile_owned_evidence(
            paths, str(case_dir), [],
            sheet_keep=ReconcileSheetEvidence({}))

        assert docs_in(paths[0]) == []
        assert not os.path.exists(source)
        assert [
            name for name in os.listdir(packet_dir)
            if name.startswith("sheet-")
        ] == []

    def test_a_bare_keep_dict_is_not_a_spellable_reconciliation(
        self, tmp_path,
    ):
        """`{}` used to mean "delete every sheet document", silently.

        The PR fixed the DEFAULT and left the value nullable, so one
        `sheet_keep or None` normalisation, or one new caller forwarding
        `attach_sheet_evidence`'s bare `{}`, puts the deleting state back.
        Neither case of the two-case value can be spelled by accident, and
        anything else is refused loudly with the documents still attached.
        """
        case_dir, paths, _ = self._attach_one(tmp_path)

        with pytest.raises(TypeError):
            cccd_ingest.reconcile_owned_evidence(
                paths, str(case_dir), [], sheet_keep={})

        surviving = docs_in(paths[0])
        assert len(surviving) == 1
        assert surviving[0]["kind"] == "pit"

    def test_the_wrapper_refuses_what_it_cannot_reconcile_with(self, tmp_path):
        """Guarding the wrapper is not enough if what it wraps is unchecked.

        `ReconcileSheetEvidence(None)` is the `sheet_keep or None`
        normalisation the docstring warns about, and it used to reach
        `keep.get(...)` and raise AttributeError from inside a reconciliation
        that is not wrapped in a try. A bare string where a set belongs is
        worse than loud: `doc_id not in sheet_keep` becomes a SUBSTRING test
        and silently keeps documents it was told to drop.
        """
        case_dir, paths, written = self._attach_one(tmp_path)

        with pytest.raises(TypeError):
            ReconcileSheetEvidence(None)
        with pytest.raises(TypeError):
            ReconcileSheetEvidence({0: "sheet-excel-d0-pit"})
        with pytest.raises(TypeError):
            ReconcileSheetEvidence({"0": {"sheet-excel-d0-pit"}})

        # Refused before anything was read or written.
        assert len(docs_in(paths[0])) == 1
        # And the shape `attach_sheet_evidence` really returns still works.
        assert cccd_ingest.reconcile_owned_evidence(
            paths, str(case_dir), [],
            sheet_keep=ReconcileSheetEvidence(written))
        assert len(docs_in(paths[0])) == 1

    def test_replacing_a_sheet_document_removes_the_image_it_replaced(
        self, tmp_path,
    ):
        """The other route to the orphan `reconcile` was taught to prevent.

        The doc id is positional (`sheet-excel-{drawing id}-{kind}`); the
        filename carries the image sha. So the same workbook slot with
        corrected content writes a NEW file and repoints the SAME document at
        it -- the document is never dropped, so nothing puts the old file in
        `removed_docs`. `app.get_page` serves it by filename anyway.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path, packets=1)
        metas[0]["rosterIdentity"] = {"cccd": ROSTER_ROWS[0]["cccd"]}
        packet_dir = os.path.dirname(paths[0])

        def read(sha: str, blob: bytes):
            path = extracted / f"tax-{sha[:4]}.png"
            path.write_bytes(blob)
            drawing = FakeDrawing(
                "drawing-0001", "tax", FakeAnchor("MST", 3),
                stored_path=str(path), sha256=sha,
            )
            return cccd_ingest.attach_sheet_evidence(
                [drawing], {"MST": MST_SHEET}, ROSTER_ROWS, metas,
                str(case_dir), paths,
            )

        read("a" * 64, b"\x89PNG\r\n\x1a\n" + b"1" * 40)
        first = docs_in(paths[0])[0]["pages"][0]["src"]
        read("b" * 64, b"\x89PNG\r\n\x1a\n" + b"2" * 40)
        second = docs_in(paths[0])[0]["pages"][0]["src"]

        assert first != second
        assert os.path.exists(second)
        # The superseded image is gone, not merely unreferenced.
        assert not os.path.exists(first)
        assert sorted(
            name for name in os.listdir(packet_dir)
            if name.startswith("sheet-")
        ) == [os.path.basename(second)]

    def test_every_owned_family_is_reconciled(self):
        """A family in `_OWNED_FAMILIES` that `_should_drop` has no branch for
        would be un-reconcilable: never dropped, never unlinked, forever. This
        fails when the two drift apart rather than letting them.
        """
        for prefix in cccd_ingest._OWNED_PREFIXES:
            assert cccd_ingest._should_drop(
                f"{prefix}nothing-produced-this", set(), set(),
            ), prefix

    def test_a_card_operation_does_not_touch_sheet_evidence(self, tmp_path):
        """The one that shipped broken, and that this test used to assert.

        `cccd_manual.assign_card` reconciles after every Gán and Gỡ and knows
        nothing about sheet evidence, so it passes no sheet keep-set. While
        that meant "keep none", one click deleted every tax document in the
        case -- silently, 200 OK, #6 straight back from REVIEW to MISSING,
        with no re-ingest route to restore it.

        Omitting the sheet keep-set now means "not my family, leave it alone".
        """
        case_dir, paths, _ = self._attach_one(tmp_path)
        assert len(docs_in(paths[0])) == 1

        # exactly what cccd_manual.py:281 does after a card assign or detach
        assert cccd_ingest.reconcile_owned_evidence(paths, str(case_dir), [])

        surviving = docs_in(paths[0])
        assert len(surviving) == 1
        assert surviving[0]["kind"] == "pit"

    def test_a_card_operation_still_clears_stale_CARD_evidence(self, tmp_path):
        # The fix must not stop the reconciler doing its actual job.
        case_dir, paths, _ = self._attach_one(tmp_path)
        manifest = json.loads(open(paths[0], encoding="utf-8").read())
        manifest["docs"].append({
            "id": cccd_ingest._owned_doc_id("cand-1", "front"),
            "kind": "id_front", "label": "CCCD", "pages": [],
        })
        open(paths[0], "w", encoding="utf-8").write(json.dumps(manifest))

        assert cccd_ingest.reconcile_owned_evidence(paths, str(case_dir), [])
        kinds = [d["kind"] for d in docs_in(paths[0])]
        assert kinds == ["pit"]


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

    def test_a_roster_row_with_no_usable_cccd_cannot_claim_a_packet(self, tmp_path):
        """The wrong-person path. `_digits("")` and `_digits("n/a")` are both
        "", and `_packet_target_index` compares empty keys as EQUAL -- so a
        second roster row with no digits could claim the first one's packet
        and receive its tax screenshot. The card path already refuses this;
        the sheet path did not, and it reaches roster rows by MST routinely.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path)
        blank = [
            {"name": "NGUYEN VAN MOT", "cccd": "", "mst": "0011000001"},
            {"name": "NGUYEN VAN HAI", "cccd": "n/a", "mst": "0011000002"},
        ]
        metas[0]["rosterIdentity"] = {"cccd": "n/a"}
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),   # resolves to NGUYEN VAN MOT
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, blank, metas, str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "blank-roster-cccd"}
        assert docs_in(paths[0]) == []

    def test_a_nine_digit_cmnd_row_still_reaches_its_packet(self, tmp_path):
        """The guard is about the EMPTY key, not the length.

        `_packet_target_index` compares digit strings for exact equality, so a
        9-digit legacy CMND matches only itself and `len(targets) != 1` still
        refuses a tie -- this is a unique, correct match. `roster_checks`
        matches a `cmnd` header by name, so these rows are expected input, and
        rejecting everything that is not 12 digits threw the screenshot away.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path)
        cmnd = [
            {"name": "NGUYEN VAN MOT", "cccd": "001100000", "mst": "0011000001"},
            {"name": "NGUYEN VAN HAI", "cccd": "001100000002",
             "mst": "0011000002"},
        ]
        metas[0]["rosterIdentity"] = {"cccd": "001100000"}
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 3),   # resolves to NGUYEN VAN MOT
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, cmnd, metas, str(case_dir), paths,
        )
        assert refused == {}
        assert set(written) == {0}
        attached = docs_in(paths[0])
        assert len(attached) == 1
        assert attached[0]["kind"] == "pit"
        assert docs_in(paths[1]) == []

    def test_two_people_sharing_a_cccd_key_cannot_borrow_each_others_packet(
        self, tmp_path,
    ):
        """The other half of the empty-key hole: length was never the guard.

        Two DIFFERENT people whose CCCD cells both fold to "0" -- a shared
        placeholder -- share the routing key. HAI has no packet; MOT does.
        Routing HAI's screenshot by that key lands it on MOT's packet, and
        `len(targets) == 1` sees a clean unique hit. One person's tax lookup
        filed under another person's payment is what this tool is least
        allowed to do, so it refuses instead.
        """
        case_dir, extracted, paths, metas = build_case(tmp_path, packets=1)
        shared = [
            {"name": "NGUYEN VAN MOT", "cccd": "0", "mst": "0011000001"},
            {"name": "TRAN THI HAI", "cccd": "0", "mst": "0011000002"},
        ]
        # The only packet is MOT's.
        metas[0]["rosterIdentity"] = {"cccd": "0"}
        drawing = FakeDrawing(
            "d0", "tax", FakeAnchor("MST", 2),   # resolves to TRAN THI HAI
            stored_path=image_at(extracted, "tax0.png"),
        )
        written, refused = cccd_ingest.attach_sheet_evidence(
            [drawing], {"MST": MST_SHEET}, shared, metas, str(case_dir), paths,
        )
        assert written == {}
        assert refused == {"d0": "several-roster-rows-for-cccd"}
        assert docs_in(paths[0]) == []

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
