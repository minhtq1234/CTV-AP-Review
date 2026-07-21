import time
from jobs import JobStore, start_job

def test_job_lifecycle_success():
    store = JobStore()
    jid = store.create(job_dir="/tmp/x")
    assert store.get(jid)["status"] == "queued"
    def fake_run(pdf, roster, job_dir, cb):
        cb("ocr", 1, 2, "packet 1"); cb("ocr", 2, 2, "packet 2")
        return {"summary": {"found": 2}, "packets": []}
    start_job(store, jid, pdf="/tmp/a.pdf", roster=None, run=fake_run)
    for _ in range(100):
        if store.get(jid)["status"] in ("done", "error"): break
        time.sleep(0.02)
    j = store.get(jid)
    assert j["status"] == "done"
    assert j["result"]["summary"]["found"] == 2
    assert j["progress"]["done"] == 2 and j["progress"]["total"] == 2

def test_job_lifecycle_error():
    store = JobStore(); jid = store.create(job_dir="/tmp/x")
    def boom(*a, **k): raise RuntimeError("nope")
    start_job(store, jid, pdf="/tmp/a.pdf", roster=None, run=boom)
    for _ in range(100):
        if store.get(jid)["status"] in ("done", "error"): break
        time.sleep(0.02)
    j = store.get(jid)
    assert j["status"] == "error" and "nope" in j["error"]

if __name__ == "__main__":
    for n,f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
