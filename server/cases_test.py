import json, os, tempfile

import cases
from cases import (
    CaseStore,
    case_status,
    compact_cccd_summary,
    needs_resubmit,
    progress_of,
)

def _pkt(index, done=False, flags=None, matched_by="cccd", rejection=None):
    fields = {}
    for k in (flags or []):
        fields[k] = {"seen": True, "flag": {"reason": "sai", "note": ""}}
    return {"index": index, "name": f"P{index}", "pages": [index * 8, index * 8 + 7],
             "confidence": "green", "matchedBy": matched_by,
             "ocrIdentity": {"cccd": "", "name": ""},
             "rosterIdentity": {"cccd": "", "name": ""},
             "review": {"done": done, "fields": fields, "rejection": rejection}}

def _pkts(dones):
    return [_pkt(i, done=d) for i, d in enumerate(dones)]

def test_needs_resubmit_on_field_flag():
    assert needs_resubmit(_pkt(0, flags=["cccd"])) is True
    assert needs_resubmit(_pkt(0)) is False

def test_a_weak_match_is_a_candidate_not_a_resubmit():
    # Superseded by Acc's rule: `cần gửi lại` counts what a person decided, and
    # a weak roster match is something the machine noticed. It is reported as a
    # candidate instead -- see TestOnlyAPersonsDecisionCountsAsResubmit.
    assert needs_resubmit(_pkt(0, matched_by="name")) is False
    assert needs_resubmit(_pkt(0, matched_by="unmatched")) is False
    assert needs_resubmit(_pkt(0, matched_by="cccd")) is False

def test_case_status_from_done_count():
    assert case_status("ready", []) == "ready"
    assert case_status("ready", [_pkt(0), _pkt(1)]) == "ready"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1)]) == "in_review"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1, done=True)]) == "done"
    assert case_status("processing", [_pkt(0, done=True)]) == "processing"

def test_progress_counts_done_and_flagged():
    pkts = [_pkt(0, done=True, flags=["cccd"]), _pkt(1, done=True), _pkt(2)]
    assert progress_of(pkts) == {"done": 2, "total": 3, "flagged": 1,
                                 "candidates": 0}

def test_rejection_counts_as_completed_and_needs_resubmission_once():
    rejection = {"reasons": ["missing_documents"], "note": ""}
    rejected = _pkt(0, done=True, rejection=rejection)
    rejected_with_flag = _pkt(
        1, done=True, flags=["cccd"], rejection=rejection,
    )
    assert needs_resubmit(rejected) is True
    assert progress_of([rejected]) == {"done": 1, "total": 1, "flagged": 1,
                                       "candidates": 0}
    assert progress_of([rejected_with_flag]) == {
        "done": 1, "total": 1, "flagged": 1,
        "candidates": 0,
    }

def test_new_packet_review_defaults_include_null_rejection():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.set_result(cid, summary=None, packets=[{
            "index": 0, "name": "Synthetic", "pages": [0, 1],
            "confidence": "green", "flags": [],
        }])
        assert s.get(cid)["packets"][0]["review"] == {
            "done": False, "fields": {}, "rejection": None,
        "overrides": {},
            "overrides": {},
        }

def test_create_list_get_roundtrip_and_reload():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="Feb batch", pdf_name="feb.pdf", roster_name=None)
        assert s.get(cid)["status"] == "processing"
        s.set_result(cid, summary={"found": 2, "rosterN": 2, "autoMerged": 0},
                     packets=_pkts([False, False]))
        assert s.get(cid)["status"] == "ready"
        assert len(s.list()) == 1 and s.list()[0]["id"] == cid
        # reload from disk (simulate restart) — persistence survives
        s2 = CaseStore(d)
        assert s2.get(cid)["status"] == "ready"
        assert s2.get(cid)["summary"]["found"] == 2

def test_set_review_updates_status_and_persists():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.set_result(cid, summary=None, packets=_pkts([False, False]))
        s.set_review(cid, 0, {"done": True, "fields": {}})
        assert s.get(cid)["status"] == "in_review"
        assert s.get(cid)["packets"][0]["review"]["done"] is True
        s.set_review(cid, 1, {
            "done": True,
            "fields": {"cccd": {"seen": True, "flag": {"reason": "sai", "note": "thiếu chữ ký"}}},
        })
        assert s.get(cid)["status"] == "done"
        reloaded = CaseStore(d).get(cid)["packets"][1]["review"]["fields"]["cccd"]
        assert reloaded["flag"]["note"] == "thiếu chữ ký"

def test_set_review_normalizes_and_roundtrips_packet_rejection():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.set_result(cid, summary=None, packets=_pkts([False]))
        s.set_review(cid, 0, {
            "done": False,
            "fields": {"name": {"seen": True, "flag": None}},
            "rejection": {
                "reasons": ["missing_signature", "missing_documents"],
                "note": "  bổ sung  ",
            },
            "overrides": {},
        })
        review = CaseStore(d).get(cid)["packets"][0]["review"]
        assert review == {
            "done": True,
            "fields": {"name": {"seen": True, "flag": None}},
            "rejection": {
                "reasons": ["missing_documents", "missing_signature"],
                "note": "bổ sung",
            },
            "overrides": {},
        }

def test_delete_removes_case():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.delete(cid)
        assert s.get(cid) is None and s.list() == []


def _write_raw_case(root: str, cid: str, status: str, error=None) -> None:
    """Write a case.json directly to disk (bypassing CaseStore), simulating
    whatever a previous process last wrote before it died/restarted."""
    case_dir = os.path.join(root, cid)
    os.makedirs(case_dir, exist_ok=True)
    case = {
        "id": cid, "name": "x", "createdAt": "2026-07-13T00:00:00", "status": status,
        "pdfName": "x.pdf", "rosterName": None, "summary": None, "error": error,
        "packets": _pkts([False]) if status not in ("processing",) else [],
    }
    with open(os.path.join(case_dir, "case.json"), "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False)


def test_reconciles_orphaned_processing_case_to_error_on_load():
    # #007: a case.json left "processing" by a now-dead process (no live
    # worker survives a restart) must be reconciled to "error" on the next
    # CaseStore construction (the startup index rebuild), not loaded as a
    # perpetual "Đang xử lý…" case.
    with tempfile.TemporaryDirectory() as d:
        _write_raw_case(d, "orphan1", status="processing")
        s = CaseStore(d)
        case = s.get("orphan1")
        assert case["status"] == "error"
        assert case["error"] == "Xử lý bị gián đoạn — vui lòng xoá và tải lại."
        # persisted back to disk, not just patched in memory
        reloaded = CaseStore(d).get("orphan1")
        assert reloaded["status"] == "error"
        assert reloaded["error"] == "Xử lý bị gián đoạn — vui lòng xoá và tải lại."

def test_reconciled_processing_case_also_normalizes_existing_packet_reviews(tmp_path):
    cid = "orphan-with-packet"
    case_dir = tmp_path / cid
    case_dir.mkdir()
    case = {
        "id": cid, "name": "x", "createdAt": None, "status": "processing",
        "pdfName": "x.pdf", "rosterName": None, "summary": None, "error": None,
        "packets": [{
            "index": 0, "confidence": "green", "matchedBy": "cccd",
            "ocrIdentity": {"cccd": "", "name": ""},
            "rosterIdentity": None,
            "review": {"done": False, "fields": {}},
        }],
    }
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")

    loaded = CaseStore(str(tmp_path)).get(cid)
    assert loaded["status"] == "error"
    assert loaded["packets"][0]["review"] == {
        "done": False, "fields": {}, "rejection": None,
        "overrides": {},
    }


def test_reconcile_leaves_other_statuses_untouched():
    # Every other lifecycle status (including a GENUINE pipeline error, whose
    # own message must not be clobbered by the "interrupted" one) survives a
    # fresh CaseStore load unchanged.
    with tempfile.TemporaryDirectory() as d:
        _write_raw_case(d, "ready1", status="ready")
        _write_raw_case(d, "review1", status="in_review")
        _write_raw_case(d, "done1", status="done")
        _write_raw_case(d, "err1", status="error", error="lỗi thật: sai định dạng PDF")

        s = CaseStore(d)
        assert s.get("ready1")["status"] == "ready"
        assert s.get("review1")["status"] == "in_review"
        assert s.get("done1")["status"] == "done"
        assert s.get("err1")["status"] == "error"
        assert s.get("err1")["error"] == "lỗi thật: sai định dạng PDF"

def test_load_migrates_old_decision_packets(tmp_path):
    cid = "old"
    d = tmp_path / cid
    d.mkdir()
    old = {"id": cid, "name": "x", "createdAt": None, "status": "in_review",
           "pdfName": "x.pdf", "rosterName": None, "summary": None, "error": None,
           "packets": [{"index": 0, "confidence": "green",
                        "decision": "approved", "rejectReason": None, "reviewedAt": "t"}]}
    (d / "case.json").write_text(json.dumps(old), encoding="utf-8")
    store = CaseStore(str(tmp_path))
    p = store.get(cid)["packets"][0]
    assert p["review"] == {"done": False, "fields": {}, "rejection": None,
                           "overrides": {}}
    assert "decision" not in p and "rejectReason" not in p and "reviewedAt" not in p
    assert p["matchedBy"] == "no-roster"

def test_load_adds_null_rejection_to_existing_review_without_changing_fields(tmp_path):
    cid = "existing-review"
    d = tmp_path / cid
    d.mkdir()
    fields = {"name": {"seen": True, "flag": {"reason": "sai", "note": "x"}}}
    case = {
        "id": cid, "name": "x", "createdAt": None, "status": "in_review",
        "pdfName": "x.pdf", "rosterName": None, "summary": None, "error": None,
        "packets": [{
            "index": 0, "confidence": "green", "matchedBy": "cccd",
            "ocrIdentity": {"cccd": "", "name": ""},
            "rosterIdentity": None,
            "review": {"done": True, "fields": fields},
        }],
    }
    (d / "case.json").write_text(json.dumps(case), encoding="utf-8")
    packet = CaseStore(str(tmp_path)).get(cid)["packets"][0]
    assert packet["review"] == {
        "done": True, "fields": fields, "rejection": None,
        "overrides": {},
    }
    persisted = json.loads((d / "case.json").read_text(encoding="utf-8"))
    assert persisted["packets"][0]["review"]["rejection"] is None


def test_cccd_workbook_metadata_persists_across_restart(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create(
        name="Synthetic",
        pdf_name="packet.pdf",
        roster_name="roster.xlsx",
        cccd_name="cards.xlsx",
    )
    workbook = {
        "status": "ready",
        "summary": {"candidates": 3, "attached": 2, "unresolved": 1},
        "mappings": [{"candidateId": "card-1", "ocrIdentity": {"cccd": "secret"}}],
    }

    store.set_result(
        cid,
        summary={"found": 1},
        packets=_pkts([False]),
        cccd_workbook=workbook,
    )

    reloaded = CaseStore(str(tmp_path)).get(cid)
    assert reloaded["cccdName"] == "cards.xlsx"
    assert reloaded["cccdWorkbook"] == workbook
    assert set(CaseStore(str(tmp_path)).list()[0]) == {
        "id", "name", "createdAt", "status", "pdfName", "progress",
    }


def test_legacy_case_normalizes_missing_cccd_fields_without_changing_review(
    tmp_path,
):
    cid = "legacy-cccd"
    case_dir = tmp_path / cid
    case_dir.mkdir()
    rejection = {
        "reasons": ["missing_signature"],
        "note": "Synthetic note",
    }
    case = {
        "id": cid,
        "name": "Synthetic",
        "createdAt": None,
        "status": "done",
        "pdfName": "packet.pdf",
        "rosterName": None,
        "summary": None,
        "error": None,
        "packets": [_pkt(0, done=True, rejection=rejection)],
    }
    (case_dir / "case.json").write_text(
        json.dumps(case),
        encoding="utf-8",
    )

    loaded = CaseStore(str(tmp_path)).get(cid)

    assert loaded["cccdName"] is None
    assert loaded["cccdWorkbook"] is None
    assert loaded["packets"][0]["review"]["rejection"] == rejection


def test_compact_cccd_summary_redacts_mappings_and_private_errors():
    workbook = {
        "status": "partial",
        "errorCode": "private-exception",
        "summary": {"candidates": "3", "attached": 2, "unresolved": 1},
        "mappings": [{"ocrIdentity": {"cccd": "000000000001"}}],
    }

    assert compact_cccd_summary(workbook) == {
        "status": "partial",
        "candidates": 3,
        "attached": 2,
        "unresolved": 1,
        "errorCode": "invalid-workbook",
    }
    assert compact_cccd_summary(None) is None


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")


class TestPurchaseTotal:
    def test_set_result_persists_the_listing_total(self, tmp_path):
        store = cases.CaseStore(str(tmp_path))
        cid = store.create("c", "in.pdf", "roster.xlsx", now="2026-08-26T00:00:00Z")

        store.set_result(cid, summary=None, packets=[],
                         purchase_total={"gross": 240_305_556,
                                         "reason": "digits-and-words-agree"})

        assert store.get(cid)["purchaseTotal"]["gross"] == 240_305_556

    def test_it_survives_a_reload_from_disk(self, tmp_path):
        store = cases.CaseStore(str(tmp_path))
        cid = store.create("c", "in.pdf", None, now="2026-08-26T00:00:00Z")
        store.set_result(cid, summary=None, packets=[],
                         purchase_total={"gross": 1_000})

        assert cases.CaseStore(str(tmp_path)).get(cid)["purchaseTotal"] == {
            "gross": 1_000,
        }

    def test_a_case_with_no_listing_records_none(self, tmp_path):
        store = cases.CaseStore(str(tmp_path))
        cid = store.create("c", "in.pdf", None, now="2026-08-26T00:00:00Z")
        store.set_result(cid, summary=None, packets=[])

        assert store.get(cid)["purchaseTotal"] is None

    def test_an_older_case_on_disk_gains_the_field(self, tmp_path):
        """Cases written before this existed must not KeyError."""
        import json
        import os

        os.makedirs(tmp_path / "old", exist_ok=True)
        with open(tmp_path / "old" / "case.json", "w", encoding="utf-8") as f:
            json.dump({"id": "old", "name": "c", "createdAt": None,
                       "status": "ready", "pdfName": "in.pdf",
                       "rosterName": None, "summary": None, "error": None,
                       "packets": []}, f)

        assert cases.CaseStore(str(tmp_path)).get("old")["purchaseTotal"] is None


# ---------------------------------------------------------------------------
# Reviewer decisions on criteria cells.
#
# `normalize_review` returns a fixed three-key dict, so any key it does not name
# is dropped — and `_ensure_packet_defaults` runs it on every load while `_load`
# writes back what changed, so a stored decision would be deleted *and the
# deletion persisted*. This shape has to exist before anything writes to it.
# ---------------------------------------------------------------------------

import criteria as _cr                                    # noqa: E402
from criteria import Status as _Status                     # noqa: E402


def _override(stt=1, document=None, frm=_Status.OK, to=_Status.NO,
              reason="tên trên hợp đồng là người khác", at="2026-08-27T00:00:00Z"):
    return _cr.Override(stt=stt, document=document or _cr.CONTRACT,
                        from_status=frm, to_status=to, reason=reason,
                        at=at, by="")


class TestNormalizeReviewKeepsDecisions:
    def test_overrides_survive_normalisation(self):
        o = _override()
        kept = cases.normalize_review(
            {"done": False, "fields": {}, "overrides": {o.key: [o.as_dict()]}})

        assert kept["overrides"] == {o.key: [o.as_dict()]}

    def test_a_review_without_them_gets_an_empty_map(self):
        assert cases.normalize_review({})["overrides"] == {}

    def test_a_malformed_overrides_value_becomes_an_empty_map(self):
        for junk in (None, [], "x", 3):
            assert cases.normalize_review({"overrides": junk})["overrides"] == {}

    def test_the_other_keys_are_untouched(self):
        out = cases.normalize_review({"done": True, "fields": {"a": {}}})
        assert out["done"] is True and out["fields"] == {"a": {}}


class TestAddingADecision:
    def _store(self, tmp_path):
        store = cases.CaseStore(str(tmp_path))
        cid = store.create("c", "in.pdf", "r.xlsx", now="2026-08-27T00:00:00Z")
        store.set_result(cid, summary=None, packets=[
            {"index": 0, "name": "A", "pages": [0, 7], "flags": [],
             "labels": [], "confidence": "green"},
        ])
        return store, cid

    def test_it_records_the_decision(self, tmp_path):
        store, cid = self._store(tmp_path)
        o = _override()

        case = store.add_override(cid, 0, o)

        assert case["packets"][0]["review"]["overrides"][o.key] == [o.as_dict()]

    def test_it_survives_a_reload_from_disk(self, tmp_path):
        store, cid = self._store(tmp_path)
        o = _override()
        store.add_override(cid, 0, o)

        reloaded = cases.CaseStore(str(tmp_path)).get(cid)

        assert reloaded["packets"][0]["review"]["overrides"][o.key] \
            == [o.as_dict()]

    def test_deciding_again_appends_rather_than_replaces(self, tmp_path):
        """An audit trail is the point. A reviewer who changes their mind leaves
        both decisions, and the engine's original view is the first record's
        `fromStatus`."""
        store, cid = self._store(tmp_path)
        first = _override(frm=_Status.OK, to=_Status.NO, at="t1")
        second = _override(frm=_Status.NO, to=_Status.OK, at="t2",
                           reason="đã xem lại bản scan, đúng")
        store.add_override(cid, 0, first)
        case = store.add_override(cid, 0, second)

        history = case["packets"][0]["review"]["overrides"][first.key]
        assert [h["at"] for h in history] == ["t1", "t2"]
        assert history[0]["fromStatus"] == "ok"      # what the engine thought

    def test_decisions_on_different_cells_are_separate(self, tmp_path):
        store, cid = self._store(tmp_path)
        a = _override(stt=1, document=_cr.CONTRACT)
        b = _override(stt=1, document=_cr.BBNT)
        store.add_override(cid, 0, a)
        case = store.add_override(cid, 0, b)

        assert set(case["packets"][0]["review"]["overrides"]) == {a.key, b.key}

    def test_an_unknown_case_or_packet_is_refused(self, tmp_path):
        store, cid = self._store(tmp_path)
        assert store.add_override("nope", 0, _override()) is None
        assert store.add_override(cid, 99, _override()) is None

    def test_it_does_not_disturb_the_field_review(self, tmp_path):
        store, cid = self._store(tmp_path)
        store.set_review(cid, 0, {"done": True, "fields": {
            "cccd": {"seen": True, "flag": {"reason": "x", "note": ""}}}})

        case = store.add_override(cid, 0, _override())
        review = case["packets"][0]["review"]

        assert review["fields"]["cccd"]["flag"]["reason"] == "x"
        assert review["done"] is True


class TestTheEffectiveDecision:
    def test_the_latest_decision_per_cell_wins(self):
        first = _override(frm=_Status.OK, to=_Status.NO, at="t1")
        second = _override(frm=_Status.NO, to=_Status.OK, at="t2", reason="y")
        review = {"overrides": {first.key: [first.as_dict(), second.as_dict()]}}

        effective = cases.effective_overrides(review)

        assert effective[first.key]["toStatus"] == "ok"
        assert effective[first.key]["at"] == "t2"

    def test_no_decisions_is_an_empty_map(self):
        assert cases.effective_overrides({}) == {}
        assert cases.effective_overrides({"overrides": {}}) == {}

    def test_an_empty_history_is_skipped(self):
        assert cases.effective_overrides({"overrides": {"01:Excel": []}}) == {}

    def test_the_result_feeds_the_engine_directly(self):
        import evaluate as ev
        o = _override(stt=21, document=_cr.CONTRACT,
                      frm=_Status.REVIEW, to=_Status.OK, reason="đã xem")
        review = {"overrides": {o.key: [o.as_dict()]}}

        manifest = {"id": "p", "docs": [
            {"id": "contract-0", "kind": "contract", "label": "HĐ", "pages": []},
        ], "fields": []}
        results = {r.stt: r for r in ev.evaluate_packet(
            manifest, None, overrides=cases.effective_overrides(review))}

        assert results[21].status is _Status.OK


class TestOnlyAPersonsDecisionCountsAsResubmit:
    """Acc's rule: `cần gửi lại` counts what a *person* decided; the engine's
    findings are candidates shown separately.

    Before this, the report counted 34 packets on the July case while the
    dashboard said 0 — and, in the other direction, a weak roster match counted
    as needing resubmission even though it is something the machine noticed, not
    something anyone decided.
    """

    def _packet(self, **kw):
        base = {"index": 0, "name": "A", "pages": [0, 7],
                "matchedBy": "cccd", "flags": [], "labels": [],
                "review": cases.normalize_review({})}
        return {**base, **kw}

    def _review(self, **kw):
        return cases.normalize_review(kw)

    def test_a_rejection_counts(self):
        p = self._packet(review=self._review(rejection={
            "reasons": ["missing_documents"], "note": ""}))
        assert cases.needs_resubmit(p) is True

    def test_a_field_a_person_flagged_counts(self):
        p = self._packet(review=self._review(fields={
            "cccd": {"seen": True, "flag": {"reason": "sai", "note": ""}}}))
        assert cases.needs_resubmit(p) is True

    def test_a_cell_a_person_decided_is_wrong_counts(self):
        o = _override(stt=23, document=_cr.BBNT, frm=_Status.REVIEW,
                      to=_Status.NO)
        p = self._packet(review=self._review(overrides={o.key: [o.as_dict()]}))
        assert cases.needs_resubmit(p) is True

    def test_a_cell_a_person_decided_is_missing_counts(self):
        o = _override(stt=23, document=_cr.BBNT, frm=_Status.REVIEW,
                      to=_Status.MISSING)
        p = self._packet(review=self._review(overrides={o.key: [o.as_dict()]}))
        assert cases.needs_resubmit(p) is True

    def test_a_cell_a_person_cleared_does_not_count(self):
        o = _override(stt=21, document=_cr.CONTRACT, frm=_Status.REVIEW,
                      to=_Status.OK)
        p = self._packet(review=self._review(overrides={o.key: [o.as_dict()]}))
        assert cases.needs_resubmit(p) is False

    def test_only_the_latest_decision_on_a_cell_counts(self):
        first = _override(stt=23, document=_cr.BBNT, frm=_Status.REVIEW,
                          to=_Status.NO, at="t1")
        second = _override(stt=23, document=_cr.BBNT, frm=_Status.NO,
                           to=_Status.OK, at="t2")
        p = self._packet(review=self._review(overrides={
            first.key: [first.as_dict(), second.as_dict()]}))
        assert cases.needs_resubmit(p) is False

    def test_a_weak_roster_match_is_no_longer_a_resubmit(self):
        """It is something the machine noticed, not something a person decided,
        so it belongs with the candidates. This changes an existing count."""
        for matched in ("name", "unmatched"):
            assert cases.needs_resubmit(self._packet(matchedBy=matched)) is False

    def test_a_clean_packet_does_not_count(self):
        assert cases.needs_resubmit(self._packet()) is False

    def test_progress_counts_only_decided_packets(self):
        o = _override(stt=23, document=_cr.BBNT, frm=_Status.REVIEW,
                      to=_Status.NO)
        packets = [
            self._packet(index=0, review=self._review(overrides={
                o.key: [o.as_dict()]})),
            self._packet(index=1, matchedBy="unmatched"),
            self._packet(index=2),
        ]
        assert cases.progress_of(packets)["flagged"] == 1


class TestWhatAPersonHasDecided:
    """The helper the resubmit gate reads, exposed so the API can report it."""

    def test_it_lists_the_cells_decided_against(self):
        bad = _override(stt=23, document=_cr.BBNT, frm=_Status.REVIEW,
                        to=_Status.NO)
        good = _override(stt=21, document=_cr.CONTRACT, frm=_Status.REVIEW,
                         to=_Status.OK)
        review = cases.normalize_review({"overrides": {
            bad.key: [bad.as_dict()], good.key: [good.as_dict()]}})

        assert cases.decided_against(review) == [bad.key]

    def test_no_decisions_is_empty(self):
        assert cases.decided_against(cases.normalize_review({})) == []
