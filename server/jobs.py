"""In-memory job registry + threaded runner for the upload/split/OCR pipeline.

Kept deliberately dumb: a dict-backed store (no persistence — this is a local,
single-user tool) and a thread-per-job runner that reports progress via a
callback closure. The `run` callable is injected so tests can exercise the
lifecycle (queued -> processing -> done/error) without a real PDF or OCR.
"""
from __future__ import annotations

import threading
import uuid


class JobStore:
    """Registry of job dicts, keyed by a uuid4 hex id.

    Job shape: `{id, status, progress, result, error, dir}` where `status` is
    one of "queued"/"processing"/"done"/"error" and `progress` is
    `{stage, done, total, detail}`.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def create(self, job_dir: str) -> str:
        jid = uuid.uuid4().hex
        self._jobs[jid] = {
            "id": jid,
            "status": "queued",
            "progress": {"stage": "queued", "done": 0, "total": 0, "detail": ""},
            "result": None,
            "error": None,
            "dir": job_dir,
        }
        return jid

    def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.update(fields)

    def set_progress(self, job_id: str, stage: str, done: int, total: int, detail: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job["progress"] = {"stage": stage, "done": done, "total": total, "detail": detail}


def start_job(store: JobStore, job_id: str, pdf: str, roster: str | None, run) -> None:
    """Spawn a daemon thread running `run(pdf, roster, job_dir, cb)`.

    On success, stores the returned dict as `result` and sets status "done".
    On exception, sets status "error" with the exception message. Returns
    immediately — callers poll `store.get(job_id)`.
    """
    store.update(job_id, status="processing")
    job = store.get(job_id)
    job_dir = job["dir"] if job else None

    def cb(stage: str, done: int, total: int, detail: str) -> None:
        store.set_progress(job_id, stage, done, total, detail)

    def target() -> None:
        try:
            result = run(pdf, roster, job_dir, cb)
            store.update(job_id, status="done", result=result)
        except Exception as e:  # noqa: BLE001 - surfaced to the caller via job["error"]
            store.update(job_id, status="error", error=str(e))

    t = threading.Thread(target=target, daemon=True)
    t.start()
