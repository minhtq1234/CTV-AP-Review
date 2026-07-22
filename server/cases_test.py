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

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
