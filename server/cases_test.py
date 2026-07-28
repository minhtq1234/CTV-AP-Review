import json, os, tempfile
from pathlib import Path

from cases import CaseStore, case_status, compact_cccd_summary, progress_of, needs_resubmit

def _pkt(index, done=False, flags=None, matched_by="cccd"):
    items = {}
    for k in (flags or []):
        items[k] = {"seen": True, "flag": {"reason": "sai", "note": ""}}
    return {"index": index, "name": f"P{index}", "pages": [index * 8, index * 8 + 7],
             "confidence": "green", "matchedBy": matched_by,
             "ocrIdentity": {"cccd": "", "name": ""},
             "rosterIdentity": {"cccd": "", "name": ""},
             "review": {"done": done, "items": items}}

def _pkts(dones):
    return [_pkt(i, done=d) for i, d in enumerate(dones)]


def _cccd_workbook(status="partial"):
    return {
        "status": status,
        "summary": {"candidates": 2, "attached": 1, "unresolved": 1},
        "errorCode": "extraction-incomplete" if status == "partial" else None,
        "mappings": [{
            "candidateId": "card-drawing-0001",
            "ocrIdentity": {"cccd": "000000000001", "name": "Synthetic A"},
            "attachedPacketIndex": 0,
        }],
    }

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
        s.set_review(cid, 0, {"done": True, "items": {}})
        assert s.get(cid)["status"] == "in_review"
        assert s.get(cid)["packets"][0]["review"]["done"] is True
        s.set_review(cid, 1, {
            "done": True,
            "items": {"A2": {"seen": True, "flag": {"reason": "sai", "note": ""}}},
        })
        assert s.get(cid)["status"] == "done"
        reloaded = CaseStore(d).get(cid)["packets"][1]["review"]["items"]["A2"]
        assert reloaded["flag"]["reason"] == "sai"

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
    assert p["review"] == {"done": False, "items": {}}
    assert "decision" not in p and "rejectReason" not in p and "reviewedAt" not in p
    assert p["matchedBy"] == "no-roster"


def test_progress_and_needs_resubmit_use_items():
    from cases import needs_resubmit, progress_of
    flagged = {"index": 0, "confidence": "green", "matchedBy": "cccd",
               "review": {"done": True, "items": {"A2": {"seen": True, "flag": {"reason": "sai", "note": ""}}}}}
    clean = {"index": 1, "confidence": "green", "matchedBy": "cccd", "review": {"done": True, "items": {}}}
    assert needs_resubmit(flagged) is True and needs_resubmit(clean) is False
    assert progress_of([flagged, clean]) == {"done": 2, "total": 2, "flagged": 1}


def test_load_migrates_fields_to_items(tmp_path):
    cid = "old"
    d = tmp_path / cid
    d.mkdir()
    old = {"id": cid, "name": "x", "createdAt": None, "status": "in_review", "pdfName": "x.pdf",
           "rosterName": None, "summary": None, "error": None,
           "packets": [{"index": 0, "confidence": "green", "matchedBy": "cccd",
                        "review": {"done": False, "fields": {"hoten": {"seen": True, "flag": None}}}}]}
    (d / "case.json").write_text(json.dumps(old), encoding="utf-8")
    p = CaseStore(str(tmp_path)).get(cid)["packets"][0]
    assert p["review"] == {"done": False, "items": {}} and "fields" not in p["review"]


def test_cccd_metadata_roundtrips_but_list_stays_compact(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create(
        name="synthetic",
        pdf_name="input.pdf",
        roster_name="roster.xlsx",
        cccd_name="cards.xlsx",
    )
    store.set_result(
        cid,
        summary={"found": 1},
        packets=[_pkt(0)],
        cccd_workbook=_cccd_workbook(),
    )

    detail = CaseStore(str(tmp_path)).get(cid)
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdWorkbook"]["mappings"][0]["candidateId"] == "card-drawing-0001"
    assert "cccdName" not in store.list()[0]
    assert "cccdWorkbook" not in store.list()[0]


def test_compact_cccd_summary_redacts_mapping_and_identity():
    summary = compact_cccd_summary(_cccd_workbook())
    assert summary == {
        "status": "partial",
        "candidates": 2,
        "attached": 1,
        "unresolved": 1,
        "errorCode": "extraction-incomplete",
    }
    assert "mappings" not in summary
    assert "cccd" not in json.dumps(summary).casefold()


def test_compact_cccd_summary_replaces_unknown_error_code_with_safe_fallback():
    workbook = _cccd_workbook()
    workbook["errorCode"] = "private OCR failure for Synthetic A"

    assert compact_cccd_summary(workbook)["errorCode"] == "invalid-workbook"


def test_legacy_case_normalizes_missing_cccd_properties(tmp_path):
    _write_raw_case(str(tmp_path), "legacy-cccd", status="ready")
    case = CaseStore(str(tmp_path)).get("legacy-cccd")
    assert case["cccdName"] is None
    assert case["cccdWorkbook"] is None


def test_delete_removes_cccd_workbook_assets_and_packet_copies(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create(
        name="synthetic",
        pdf_name="input.pdf",
        roster_name="roster.xlsx",
        cccd_name="cards.xlsx",
    )
    case_dir = Path(store.case_dir(cid))
    (case_dir / "cccd.xlsx").write_bytes(b"synthetic")
    (case_dir / "cccd-assets").mkdir()
    (case_dir / "cccd-assets" / "drawing-0001.png").write_bytes(b"synthetic")
    (case_dir / "packets" / "0").mkdir(parents=True)
    (case_dir / "packets" / "0" / "cccd-front.png").write_bytes(b"synthetic")

    store.delete(cid)

    assert not case_dir.exists()
    assert store.get(cid) is None


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
