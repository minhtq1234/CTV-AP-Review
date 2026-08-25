import json, os, tempfile
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

def test_needs_resubmit_on_weak_match():
    assert needs_resubmit(_pkt(0, matched_by="name")) is True
    assert needs_resubmit(_pkt(0, matched_by="unmatched")) is True
    assert needs_resubmit(_pkt(0, matched_by="cccd")) is False

def test_case_status_from_done_count():
    assert case_status("ready", []) == "ready"
    assert case_status("ready", [_pkt(0), _pkt(1)]) == "ready"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1)]) == "in_review"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1, done=True)]) == "done"
    assert case_status("processing", [_pkt(0, done=True)]) == "processing"

def test_progress_counts_done_and_flagged():
    pkts = [_pkt(0, done=True, flags=["cccd"]), _pkt(1, done=True), _pkt(2)]
    assert progress_of(pkts) == {"done": 2, "total": 3, "flagged": 1}

def test_rejection_counts_as_completed_and_needs_resubmission_once():
    rejection = {"reasons": ["missing_documents"], "note": ""}
    rejected = _pkt(0, done=True, rejection=rejection)
    rejected_with_flag = _pkt(
        1, done=True, flags=["cccd"], rejection=rejection,
    )
    assert needs_resubmit(rejected) is True
    assert progress_of([rejected]) == {"done": 1, "total": 1, "flagged": 1}
    assert progress_of([rejected_with_flag]) == {
        "done": 1, "total": 1, "flagged": 1,
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
        })
        review = CaseStore(d).get(cid)["packets"][0]["review"]
        assert review == {
            "done": True,
            "fields": {"name": {"seen": True, "flag": None}},
            "rejection": {
                "reasons": ["missing_documents", "missing_signature"],
                "note": "bổ sung",
            },
        }

def test_delete_removes_case():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.delete(cid)
        assert s.get(cid) is None and s.list() == []


def test_create_revision_links_cases_without_copying_reviews(tmp_path):
    store = CaseStore(str(tmp_path))
    source = store.create(
        "August display label", "batch.pdf", "roster.xlsx", "2026-08-25T00:00:00Z",
    )
    store.set_result(
        source,
        {"found": 1, "roster_n": 2},
        [_pkt(0, done=True, flags=["cccd"])],
    )

    revision = store.create_revision(source, "2026-08-25T00:01:00Z")

    revised = store.get(revision)
    original = store.get(source)
    assert revised["sourceCaseId"] == source
    assert revised["revisionNumber"] == 1
    assert revised["name"] == "batch.pdf"
    assert revised["pdfName"] == "batch.pdf"
    assert revised["rosterName"] == "roster.xlsx"
    assert original["revisionIds"] == [revision]
    assert revised["packets"] == []
    assert revised["summary"] is None
    assert revised["boundaryResolution"] is None


def test_revision_lineage_and_empty_reviews_survive_restart(tmp_path):
    store = CaseStore(str(tmp_path))
    source = store.create("batch.pdf", "batch.pdf", None, "2026-08-25T00:00:00Z")
    store.set_result(source, {"found": 1}, [_pkt(0, done=True)])
    revision = store.create_revision(source, "2026-08-25T00:01:00Z")

    reloaded = CaseStore(str(tmp_path))
    assert reloaded.get(source)["revisionIds"] == [revision]
    assert reloaded.get(revision)["sourceCaseId"] == source
    assert reloaded.get(revision)["revisionNumber"] == 1
    assert reloaded.get(revision)["packets"] == []


def test_set_boundary_resolution_persists_without_mutating_packet_reviews(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create("batch.pdf", "batch.pdf", None, "2026-08-25T00:00:00Z")
    store.set_result(cid, {"found": 1}, [_pkt(0, done=True, flags=["cccd"])])
    before = json.dumps(store.get(cid)["packets"], ensure_ascii=False, sort_keys=True)
    resolution = {
        "action": "keep-current",
        "starts": [0, 8],
        "reasons": ["multiple-contract-starts"],
        "resolvedAt": "2026-08-25T00:01:00Z",
    }

    updated = store.set_boundary_resolution(cid, resolution)

    assert updated["boundaryResolution"] == resolution
    assert json.dumps(updated["packets"], ensure_ascii=False, sort_keys=True) == before
    reloaded = CaseStore(str(tmp_path)).get(cid)
    assert reloaded["boundaryResolution"] == resolution
    assert json.dumps(reloaded["packets"], ensure_ascii=False, sort_keys=True) == before
    assert "reviewerName" not in reloaded["boundaryResolution"]


def test_load_migrates_boundary_defaults_without_changing_reviews(tmp_path):
    cid = "legacy-boundary"
    case_dir = tmp_path / cid
    case_dir.mkdir()
    packet = _pkt(0, done=True, flags=["cccd"])
    legacy = {
        "id": cid, "name": "x", "createdAt": None, "status": "done",
        "pdfName": "x.pdf", "rosterName": None, "summary": None,
        "error": None, "packets": [packet],
    }
    (case_dir / "case.json").write_text(json.dumps(legacy), encoding="utf-8")

    loaded = CaseStore(str(tmp_path)).get(cid)

    assert loaded["sourceCaseId"] is None
    assert loaded["revisionIds"] == []
    assert loaded["revisionNumber"] == 0
    assert loaded["boundaryResolution"] is None
    assert loaded["packets"] == [packet]
    persisted = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    assert persisted["packets"] == [packet]


def test_deleting_revision_does_not_delete_source(tmp_path):
    store = CaseStore(str(tmp_path))
    source = store.create("batch.pdf", "batch.pdf", None, "2026-08-25T00:00:00Z")
    revision = store.create_revision(source, "2026-08-25T00:01:00Z")

    store.delete(revision)

    assert store.get(source) is not None
    assert store.get(source)["revisionIds"] == [revision]
    assert CaseStore(str(tmp_path)).get(source) is not None


def test_deleting_source_leaves_revision_usable_with_lineage(tmp_path):
    store = CaseStore(str(tmp_path))
    source = store.create("batch.pdf", "batch.pdf", None, "2026-08-25T00:00:00Z")
    revision = store.create_revision(source, "2026-08-25T00:01:00Z")

    store.delete(source)

    reloaded_revision = CaseStore(str(tmp_path)).get(revision)
    assert reloaded_revision is not None
    assert reloaded_revision["sourceCaseId"] == source
    store.set_result(revision, {"found": 1}, [_pkt(0)])
    assert store.get(revision)["packets"][0]["index"] == 0


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
    assert p["review"] == {"done": False, "fields": {}, "rejection": None}
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
