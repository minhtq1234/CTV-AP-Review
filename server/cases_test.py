import json, os, tempfile
from cases import CaseStore, case_status, progress_of

def _pkts(decisions):
    return [{"index": i, "name": f"P{i}", "pages": [i*8, i*8+7], "confidence": "green",
             "flags": [], "decision": d, "rejectReason": None, "reviewedAt": None}
            for i, d in enumerate(decisions)]

def test_case_status_transitions():
    assert case_status("processing", _pkts([])) == "processing"
    assert case_status("ready", _pkts(["pending","pending"])) == "ready"
    assert case_status("ready", _pkts(["approved","pending"])) == "in_review"
    assert case_status("ready", _pkts(["approved","rejected"])) == "done"

def test_progress_counts_decided_and_flagged():
    pk = _pkts(["approved","pending","pending"])
    pk[1]["confidence"] = "amber"
    assert progress_of(pk) == {"decided": 1, "total": 3, "flagged": 1}

def test_create_list_get_roundtrip_and_reload():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="Feb batch", pdf_name="feb.pdf", roster_name=None)
        assert s.get(cid)["status"] == "processing"
        s.set_result(cid, summary={"found": 2, "rosterN": 2, "autoMerged": 0},
                     packets=_pkts(["pending","pending"]))
        assert s.get(cid)["status"] == "ready"
        assert len(s.list()) == 1 and s.list()[0]["id"] == cid
        # reload from disk (simulate restart) — persistence survives
        s2 = CaseStore(d)
        assert s2.get(cid)["status"] == "ready"
        assert s2.get(cid)["summary"]["found"] == 2

def test_set_decision_updates_status_and_persists():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.set_result(cid, summary=None, packets=_pkts(["pending","pending"]))
        s.set_decision(cid, 0, "approved", None, now="2026-07-13T00:00:00")
        assert s.get(cid)["status"] == "in_review"
        assert s.get(cid)["packets"][0]["decision"] == "approved"
        s.set_decision(cid, 1, "rejected", "thiếu chữ ký", now="2026-07-13T00:01:00")
        assert s.get(cid)["status"] == "done"
        assert CaseStore(d).get(cid)["packets"][1]["rejectReason"] == "thiếu chữ ký"

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
        "packets": _pkts(["pending"]) if status not in ("processing",) else [],
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

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
